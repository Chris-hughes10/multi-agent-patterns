"""DAG-based execution for the Planner pattern.

Provides data structures and executor for dependency-aware task execution.
The Planner creates a DAG upfront, and the DAGExecutor runs it with
parallel execution of independent steps.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from youtube_goal_agents.infra.session import ExecutionStep, Session

# Import shared components from youtube_goal_agents
from youtube_goal_agents.models.handoff import PartialResult

if TYPE_CHECKING:
    from youtube_goal_agents.agents.base import BaseAgent
    from youtube_goal_agents.infra.registry import AgentRegistry

logger = logging.getLogger("youtube_agent_planner.dag_executor")


class StepStatus(Enum):
    """Status of a DAG step."""

    PENDING = "pending"
    READY = "ready"  # Dependencies satisfied, ready to run
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DAGStep:
    """A single step in the execution DAG.

    Each step represents a task to be executed by a specific agent.
    Steps can depend on other steps, and their inputs can reference
    outputs from previous steps using variable syntax ($step_id.field).

    :param id: Unique identifier for this step
    :param agent_name: Name of the agent to execute this step
    :param description: Human-readable description of what this step does
    :param input_template: Input data, may contain variable references ($step_id.field)
    :param depends_on: List of step IDs that must complete before this step
    :param status: Current execution status
    :param result: Output data after execution
    :param error: Error message if failed
    """

    id: str
    agent_name: str
    description: str
    input_template: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None

    def is_ready(self, completed_steps: set[str]) -> bool:
        """Check if all dependencies are satisfied.

        :param completed_steps: Set of completed step IDs
        :return: True if all dependencies are in completed_steps
        """
        return all(dep in completed_steps for dep in self.depends_on)


@dataclass
class ExecutionDAG:
    """Directed Acyclic Graph representing an execution plan.

    The DAG contains steps with dependencies. Steps without dependencies
    can run in parallel. The executor runs steps as their dependencies
    are satisfied.

    :param goal: The original user goal this DAG addresses
    :param steps: List of steps in the DAG
    """

    goal: str
    steps: list[DAGStep] = field(default_factory=list)

    def get_step(self, step_id: str) -> DAGStep | None:
        """Get a step by ID.

        :param step_id: Step ID to find
        :return: DAGStep or None
        """
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_ready_steps(self, completed_steps: set[str]) -> list[DAGStep]:
        """Get all steps that are ready to run.

        :param completed_steps: Set of completed step IDs
        :return: List of steps ready to execute
        """
        return [
            step
            for step in self.steps
            if step.status == StepStatus.PENDING and step.is_ready(completed_steps)
        ]

    def get_pending_steps(self) -> list[DAGStep]:
        """Get all pending steps.

        :return: List of pending steps
        """
        return [step for step in self.steps if step.status == StepStatus.PENDING]

    def is_complete(self) -> bool:
        """Check if all steps are complete (or failed/skipped).

        :return: True if no pending or running steps
        """
        return all(
            step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)
            for step in self.steps
        )

    def get_final_results(self) -> dict[str, Any]:
        """Collect results from all completed steps.

        :return: Dict mapping step_id -> result
        """
        return {step.id: step.result for step in self.steps if step.status == StepStatus.COMPLETED}

    def validate(self) -> list[str]:
        """Validate the DAG structure.

        Checks for:
        - Duplicate step IDs
        - References to non-existent steps
        - Circular dependencies

        :return: List of validation errors (empty if valid)
        """
        errors: list[str] = []
        step_ids = {step.id for step in self.steps}

        # Check for duplicates
        if len(step_ids) != len(self.steps):
            errors.append("Duplicate step IDs found")

        # Check dependencies exist
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"Step '{step.id}' depends on non-existent step '{dep}'")

        # Check for cycles using DFS
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def has_cycle(step_id: str) -> bool:
            visited.add(step_id)
            rec_stack.add(step_id)

            step = self.get_step(step_id)
            if step:
                for dep in step.depends_on:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True

            rec_stack.remove(step_id)
            return False

        for step in self.steps:
            if step.id not in visited:
                if has_cycle(step.id):
                    errors.append("Circular dependency detected")
                    break

        return errors

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionDAG":
        """Create a DAG from a dictionary (e.g., parsed from LLM JSON output).

        :param data: Dict with 'goal' and 'steps' keys
        :return: ExecutionDAG instance
        """
        steps = []
        for step_data in data.get("steps", []):
            steps.append(
                DAGStep(
                    id=step_data["id"],
                    agent_name=step_data.get("agent", step_data.get("agent_name", "")),
                    description=step_data.get("description", ""),
                    input_template=step_data.get("input", step_data.get("input_template", {})),
                    depends_on=step_data.get("depends_on", []),
                )
            )
        return cls(goal=data.get("goal", ""), steps=steps)


class StepExecutionError(Exception):
    """Raised when a DAG step fails to execute."""

    def __init__(self, step_id: str, message: str) -> None:
        self.step_id = step_id
        super().__init__(f"Step '{step_id}' failed: {message}")


class DAGExecutor:
    """Executes a DAG with dependency tracking and parallel execution.

    The executor:
    1. Finds ready steps (dependencies satisfied)
    2. Executes ready steps in parallel
    3. Resolves variable references in step inputs
    4. Tracks results in the session
    5. Handles failures with optional re-planning

    :param registry: Agent registry for finding agents
    :param session: Session for storing results and tracking execution
    :param planner: Optional planner for re-planning on failure
    :param max_replans: Maximum number of re-plan attempts
    :param max_concurrent: Maximum concurrent step executions
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        session: Session,
        planner: "BaseAgent | None" = None,
        max_replans: int = 3,
        max_concurrent: int = 5,
    ) -> None:
        """Initialize the executor.

        :param registry: Registry for finding agents
        :param session: Session for state management
        :param planner: Optional planner for re-planning
        :param max_replans: Max re-plan attempts on failure
        :param max_concurrent: Max parallel step executions
        """
        self._registry = registry
        self._session = session
        self._planner = planner
        self._max_replans = max_replans
        self._max_concurrent = max_concurrent
        self._replan_count = 0
        self._completed_steps: set[str] = set()
        self._step_results: dict[str, Any] = {}

    async def execute(self, dag: ExecutionDAG) -> dict[str, Any] | PartialResult:
        """Execute the DAG and return results.

        :param dag: The execution DAG
        :return: Dict of results or PartialResult on failure
        """
        # Validate DAG first
        errors = dag.validate()
        if errors:
            return PartialResult(
                error=f"Invalid DAG: {'; '.join(errors)}",
                partial_data={},
            )

        self._completed_steps.clear()
        self._step_results.clear()

        try:
            await self._execute_dag(dag)
            return dag.get_final_results()

        except StepExecutionError as e:
            if self._planner and self._replan_count < self._max_replans:
                return await self._handle_failure_with_replan(dag, e)
            else:
                return PartialResult(
                    error=str(e),
                    partial_data=self._step_results,
                    completed_steps=list(self._completed_steps),
                )

    async def _execute_dag(self, dag: ExecutionDAG) -> None:
        """Execute all steps in the DAG.

        :param dag: The DAG to execute
        :raises StepExecutionError: If a step fails
        """
        while not dag.is_complete():
            # Get all ready steps
            ready_steps = dag.get_ready_steps(self._completed_steps)

            if not ready_steps:
                # No ready steps but DAG not complete - might be stuck
                pending = dag.get_pending_steps()
                if pending:
                    step_ids = [s.id for s in pending]
                    raise StepExecutionError(
                        step_ids[0],
                        f"Stuck: steps {step_ids} have unsatisfied dependencies",
                    )
                break

            # Execute ready steps in parallel (up to max_concurrent)
            semaphore = asyncio.Semaphore(self._max_concurrent)

            async def execute_with_semaphore(step: DAGStep) -> None:
                async with semaphore:
                    await self._execute_step(step)

            await asyncio.gather(
                *[execute_with_semaphore(step) for step in ready_steps],
                return_exceptions=False,
            )

    async def _execute_step(self, step: DAGStep) -> None:
        """Execute a single step.

        :param step: Step to execute
        :raises StepExecutionError: If execution fails
        """
        import time

        step.status = StepStatus.RUNNING
        start_time = time.time()

        # Resolve variable references in input
        try:
            resolved_input = self._resolve_variables(step.input_template)
        except (KeyError, IndexError) as e:
            step.status = StepStatus.FAILED
            step.error = f"Failed to resolve input variables: {e}"
            raise StepExecutionError(step.id, step.error)

        # Find the agent
        try:
            agent = self._registry.get_agent(step.agent_name)
        except KeyError:
            step.status = StepStatus.FAILED
            step.error = f"Agent '{step.agent_name}' not found"
            raise StepExecutionError(step.id, step.error)

        # Record execution step
        exec_step = ExecutionStep.create(
            agent_name=agent.name,
            action="execute",
            task_id=step.id,
            input_state_keys=list(resolved_input.keys()) if isinstance(resolved_input, dict) else [],
        )

        # Execute
        try:
            from youtube_goal_agents.models import Task

            # Build description from step description and resolved input
            if isinstance(resolved_input, dict):
                input_str = "\n".join(f"- {k}: {v}" for k, v in resolved_input.items())
                description = f"{step.description}\n\nInput:\n{input_str}"
            else:
                description = f"{step.description}\n\nInput: {resolved_input}"

            task = Task(
                description=description,
                required_capabilities=agent.capabilities,
                context=resolved_input if isinstance(resolved_input, dict) else {"input": resolved_input},
            )

            result = await agent.execute(task)

            if result.success:
                step.status = StepStatus.COMPLETED
                step.result = result.data
                self._completed_steps.add(step.id)
                self._step_results[step.id] = result.data

                # Store in session for variable resolution
                self._session.store(
                    step.id,
                    result.data,
                    metadata={"agent": agent.name, "step_description": step.description},
                )

                exec_step.action = "complete"
                exec_step.output_state_keys = [step.id]
            else:
                step.status = StepStatus.FAILED
                step.error = result.error
                exec_step.action = "error"
                exec_step.error = result.error
                raise StepExecutionError(step.id, result.error or "Unknown error")

        except StepExecutionError:
            raise
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            exec_step.action = "error"
            exec_step.error = str(e)
            raise StepExecutionError(step.id, str(e))
        finally:
            exec_step.duration_ms = (time.time() - start_time) * 1000
            self._session.record_step(exec_step)

    def _resolve_variables(self, template: Any) -> Any:
        """Resolve variable references in a template.

        Variables use the format $step_id.field or $step_id.

        :param template: Template value (may be dict, list, or string)
        :return: Resolved value
        """
        if isinstance(template, str):
            if template.startswith("$"):
                # Full variable reference
                return self._session.resolve(template)
            else:
                # Check for embedded variables
                import re

                pattern = r"\$([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*|\[\d+\])*)"
                matches = re.findall(pattern, template)
                if matches:
                    result = template
                    for match in matches:
                        var_path = f"${match}"
                        try:
                            value = self._session.resolve(var_path)
                            result = result.replace(var_path, str(value))
                        except (KeyError, IndexError):
                            pass  # Leave unresolved variables as-is
                    return result
                return template

        elif isinstance(template, dict):
            return {k: self._resolve_variables(v) for k, v in template.items()}

        elif isinstance(template, list):
            return [self._resolve_variables(item) for item in template]

        else:
            return template

    async def _handle_failure_with_replan(
        self,
        dag: ExecutionDAG,
        error: StepExecutionError,
    ) -> dict[str, Any] | PartialResult:
        """Handle a step failure by asking the planner to re-plan.

        :param dag: The current DAG
        :param error: The error that occurred
        :return: Results or PartialResult
        """
        self._replan_count += 1
        logger.info(f"Re-planning after failure (attempt {self._replan_count}/{self._max_replans})")

        if not self._planner:
            return PartialResult(
                error=str(error),
                partial_data=self._step_results,
                completed_steps=list(self._completed_steps),
            )

        # TODO: Implement re-planning logic
        # For now, just return the partial result
        return PartialResult(
            error=f"Step failed and re-planning not yet implemented: {error}",
            partial_data=self._step_results,
            completed_steps=list(self._completed_steps),
        )


async def run_with_planner(
    registry: "AgentRegistry",
    dag: ExecutionDAG,
    session: Session | None = None,
) -> dict[str, Any] | PartialResult:
    """Convenience function to run a DAG with the executor.

    :param registry: Agent registry
    :param dag: Execution DAG
    :param session: Optional session (creates new if not provided)
    :return: Results or PartialResult
    """
    session = session or Session()
    executor = DAGExecutor(registry, session)
    return await executor.execute(dag)
