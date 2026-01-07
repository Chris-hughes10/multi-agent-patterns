"""SynthesizerAgent - User-facing entry point for multi-agent coordination.

The Synthesizer is the single point of contact for users. It:
- Receives all user messages
- Maintains the Session (conversation memory)
- Delegates work to either Planner (DAG approach) or agents (autonomous approach)
- Aggregates results and produces the final user-facing response
- Does NOT coordinate every agent step (unlike V1 orchestrator)
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent.infra.client import get_chat_client
from youtube_agent_v2.core.intent_router import IntentRouter, get_default_router
from youtube_agent_v2.core.loop_detector import LoopDetector
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult
from youtube_agent_v2.core.session import ExecutionStep, Session
from youtube_agent_v2.patterns.dag_executor import DAGExecutor

if TYPE_CHECKING:
    from youtube_agent_v2.agents.planner import PlannerAgent
    from youtube_agent_v2.core.base_agent import BaseAgent
    from youtube_agent_v2.core.registry import AgentRegistry


SYNTHESIZER_INSTRUCTIONS = """You are a Synthesizer Agent - the user's primary assistant for YouTube video research.

Your role is to:
1. Understand what the user wants to accomplish
2. Present results in a clear, helpful format
3. Maintain context across conversation turns
4. Summarize and synthesize information from multiple sources

You do NOT directly search, fetch transcripts, or summarize - other specialized agents do that work.
You receive their results and present them to the user in a coherent way.

When presenting results:
- Be concise but comprehensive
- Highlight key findings
- Reference sources (video titles, IDs) when relevant
- Suggest follow-up actions the user might want to take

If something went wrong during processing, explain what happened and suggest alternatives."""


class SynthesizerAgent:
    """User-facing agent that coordinates multi-agent workflows.

    The Synthesizer serves as the entry point for user requests and
    coordinates work across specialized agents using either:
    - Planner + DAG: Creates execution plan upfront, then executes
    - Autonomous: Agents hand off to each other based on goals

    Unlike BaseAgent subclasses, the Synthesizer doesn't have capabilities -
    it delegates all work to other agents.

    :param registry: Agent registry for finding capable agents
    :param client: Optional chat client for response synthesis
    :param router: Optional intent router for autonomous mode
    :param session: Optional existing session (creates new if not provided)
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,
        router: IntentRouter | None = None,
        session: Session | None = None,
    ) -> None:
        """Initialize the synthesizer.

        :param registry: Registry of available agents
        :param client: Optional chat client
        :param router: Optional intent router
        :param session: Optional existing session
        """
        self._registry = registry
        self._client = client or get_chat_client()
        self._router = router or get_default_router()
        self._session = session or Session()
        self._chat_agent: ChatAgent | None = None
        self._loop_detector = LoopDetector(max_visits=3, window_size=15)

    @property
    def name(self) -> str:
        """Return agent name."""
        return "synthesizer"

    @property
    def session(self) -> Session:
        """Access the session for external inspection."""
        return self._session

    def _get_chat_agent(self) -> ChatAgent:
        """Get or create the ChatAgent for response synthesis."""
        if self._chat_agent is None:
            self._chat_agent = ChatAgent(
                chat_client=self._client,
                name=self.name,
                instructions=SYNTHESIZER_INSTRUCTIONS,
                tools=[],  # Synthesizer doesn't use tools directly
            )
        return self._chat_agent

    async def process_request(
        self,
        user_request: str,
        pattern: str = "autonomous",
    ) -> str:
        """Process a user request through the multi-agent system.

        :param user_request: The user's natural language request
        :param pattern: Coordination pattern ("autonomous" or "planner")
        :return: Synthesized response for the user
        """
        # Store the request in session
        self._session.store(
            "last_request",
            user_request,
            metadata={"type": "user_request"},
        )

        if pattern == "planner":
            result = await self._process_with_planner(user_request)
        else:
            result = await self._process_autonomous(user_request)

        # Synthesize the final response
        return await self._synthesize_response(user_request, result)

    async def _process_autonomous(
        self,
        user_request: str,
    ) -> HandoffResult | PartialResult:
        """Process request using autonomous agent coordination.

        Agents receive the goal and current state, reason about what
        to do, and hand off to the next agent as needed.

        :param user_request: The user's request
        :return: Final result or partial result if errors occurred
        """
        # Find the first agent to handle this request
        current_agent = await self._router.find_agent_for_intent(
            user_request,
            self._registry,
        )

        if current_agent is None:
            return PartialResult(
                error="No suitable agent found for this request",
                partial_data={"request": user_request},
            )

        # Initialize task state
        state: dict[str, Any] = {}
        goal = user_request
        task_id = f"task_{self._session.id}"

        import time

        # Execute agent chain
        while True:
            start_time = time.time()

            # Record step start
            step = ExecutionStep.create(
                agent_name=current_agent.name,
                action="execute",
                task_id=task_id,
                input_state_keys=list(state.keys()),
            )

            try:
                # Check if agent has autonomous execution
                if hasattr(current_agent, "execute_autonomous"):
                    result = await current_agent.execute_autonomous(goal, state)
                else:
                    # Fall back to regular execution with context
                    from youtube_agent_v2.core import Task

                    task = Task(
                        description=f"Goal: {goal}\nContext: {state}",
                        required_capabilities=current_agent.capabilities,
                        context=state,
                    )
                    task_result = await current_agent.execute(task)

                    # Convert TaskResult to HandoffResult
                    if task_result.success:
                        result = HandoffResult.complete(task_result.data)
                    else:
                        result = PartialResult(
                            error=task_result.error or "Unknown error",
                            partial_data=state,
                        )

                # Calculate duration
                duration_ms = (time.time() - start_time) * 1000

            except Exception as e:
                # Record error step
                step.action = "error"
                step.error = str(e)
                step.duration_ms = (time.time() - start_time) * 1000
                self._session.record_step(step)

                return PartialResult(
                    error=f"Agent {current_agent.name} failed: {e}",
                    partial_data=state,
                    completed_steps=[s.agent_name for s in self._session.get_execution_path()],
                )

            # Handle result
            if isinstance(result, PartialResult):
                step.action = "error"
                step.error = result.error
                step.duration_ms = duration_ms
                self._session.record_step(step)
                return result

            if result.is_complete:
                # Store result and return
                step.action = "complete"
                step.duration_ms = duration_ms
                step.output_state_keys = ["final_result"]
                self._session.record_step(step)

                self._session.store(
                    "final_result",
                    result.result,
                    metadata={"agent": current_agent.name, "task_id": task_id},
                )
                return result

            # Handoff to next agent
            step.action = "handoff"
            step.intent = result.intent
            step.duration_ms = duration_ms

            # Update state with any new data
            if result.state:
                state.update(result.state)
                step.output_state_keys = list(result.state.keys())

            self._session.record_step(step)

            # Check for loops before finding next agent
            if self._loop_detector.check_for_loop(self._session.get_execution_path()):
                cycle = self._loop_detector.detect_cycle(self._session.get_execution_path())
                return PartialResult(
                    error=f"Loop detected in agent handoffs: {' → '.join(cycle or ['unknown'])}",
                    partial_data=state,
                    completed_steps=[s.agent_name for s in self._session.get_execution_path()],
                )

            # Find next agent based on intent
            next_agent = await self._router.find_agent_for_intent(
                result.intent or goal,
                self._registry,
            )

            if next_agent is None:
                return PartialResult(
                    error=f"No agent found for intent: {result.intent}",
                    partial_data=state,
                    completed_steps=[s.agent_name for s in self._session.get_execution_path()],
                )

            current_agent = next_agent

    async def _process_with_planner(
        self,
        user_request: str,
    ) -> HandoffResult | PartialResult:
        """Process request using Planner + DAG execution.

        Creates an execution plan upfront, then executes it.
        If execution fails, attempts re-planning with partial results.

        :param user_request: The user's request
        :return: Final result or partial result if errors occurred
        """
        import time

        from youtube_agent_v2.agents.planner import PlannerAgent

        task_id = f"task_{self._session.id}"

        # Create the planner
        planner = PlannerAgent(registry=self._registry, client=self._client)

        # Record planning step
        plan_step = ExecutionStep.create(
            agent_name=planner.name,
            action="execute",
            task_id=task_id,
            input_state_keys=["user_request"],
        )
        start_time = time.time()

        try:
            # Create the execution plan
            dag = await planner.create_plan(user_request)
            plan_step.duration_ms = (time.time() - start_time) * 1000
            plan_step.output_state_keys = ["execution_dag"]
            self._session.record_step(plan_step)

            # Store the plan in session
            self._session.store(
                "execution_dag",
                {"goal": dag.goal, "steps": [s.id for s in dag.steps]},
                metadata={"task_id": task_id},
            )

        except ValueError as e:
            # Planning failed
            plan_step.action = "error"
            plan_step.error = str(e)
            plan_step.duration_ms = (time.time() - start_time) * 1000
            self._session.record_step(plan_step)

            return PartialResult(
                error=f"Planning failed: {e}",
                partial_data={"request": user_request},
            )

        # Create the DAG executor
        executor = DAGExecutor(registry=self._registry, session=self._session)

        # Record execution step
        exec_step = ExecutionStep.create(
            agent_name="dag_executor",
            action="execute",
            task_id=task_id,
            input_state_keys=["execution_dag"],
        )
        start_time = time.time()

        try:
            # Execute the DAG
            result = await executor.execute(dag)
            exec_step.duration_ms = (time.time() - start_time) * 1000

            if isinstance(result, PartialResult):
                # Execution failed - attempt re-planning
                exec_step.action = "error"
                exec_step.error = result.error
                self._session.record_step(exec_step)

                # Try to re-plan
                replan_result = await self._attempt_replan(
                    planner=planner,
                    executor=executor,
                    original_goal=user_request,
                    partial_result=result,
                    task_id=task_id,
                )
                if replan_result is not None:
                    return replan_result

                # Re-planning failed or wasn't possible
                return result

            # Success - return as HandoffResult
            exec_step.action = "complete"
            exec_step.output_state_keys = list(result.keys()) if isinstance(result, dict) else ["result"]
            self._session.record_step(exec_step)

            # Store final result
            self._session.store(
                "final_result",
                result,
                metadata={"task_id": task_id, "pattern": "planner"},
            )

            return HandoffResult.complete(result)

        except Exception as e:
            exec_step.action = "error"
            exec_step.error = str(e)
            exec_step.duration_ms = (time.time() - start_time) * 1000
            self._session.record_step(exec_step)

            return PartialResult(
                error=f"DAG execution failed: {e}",
                partial_data={"request": user_request},
                completed_steps=[s.agent_name for s in self._session.get_execution_path()],
            )

    async def _attempt_replan(
        self,
        planner: "PlannerAgent",
        executor: DAGExecutor,
        original_goal: str,
        partial_result: PartialResult,
        task_id: str,
    ) -> HandoffResult | PartialResult | None:
        """Attempt to re-plan after a DAG execution failure.

        :param planner: The planner agent to use
        :param executor: The DAG executor
        :param original_goal: The original user request
        :param partial_result: The partial result from failed execution
        :param task_id: Current task ID
        :return: New result if re-planning succeeded, None if not attempted
        """
        import time

        # Only re-plan if we have meaningful partial data
        if not partial_result.partial_data:
            return None

        # Extract failure info
        failed_step = partial_result.completed_steps[-1] if partial_result.completed_steps else "unknown"
        completed_results = partial_result.partial_data

        # Record re-planning step
        replan_step = ExecutionStep.create(
            agent_name=planner.name,
            action="execute",
            task_id=task_id,
            input_state_keys=["partial_result", "error"],
            intent="replan",
        )
        start_time = time.time()

        try:
            # Create revised plan
            revised_dag = await planner.replan(
                original_goal=original_goal,
                completed_results=completed_results,
                failed_step=failed_step,
                error=partial_result.error or "Unknown error",
            )
            replan_step.duration_ms = (time.time() - start_time) * 1000
            replan_step.output_state_keys = ["revised_dag"]
            self._session.record_step(replan_step)

            # Execute the revised plan
            result = await executor.execute(revised_dag)

            if isinstance(result, PartialResult):
                # Re-planning also failed - return original error
                return None

            return HandoffResult.complete(result)

        except ValueError:
            # Re-planning failed to produce valid DAG
            replan_step.action = "error"
            replan_step.duration_ms = (time.time() - start_time) * 1000
            self._session.record_step(replan_step)
            return None

    async def _synthesize_response(
        self,
        user_request: str,
        result: HandoffResult | PartialResult,
    ) -> str:
        """Synthesize a user-friendly response from the result.

        :param user_request: Original user request
        :param result: Result from agent coordination
        :return: User-friendly response string
        """
        chat_agent = self._get_chat_agent()

        # Build context for synthesis
        execution_summary = self._session.get_path_summary()

        if isinstance(result, PartialResult):
            prompt = f"""The user asked: "{user_request}"

Unfortunately, there was an issue during processing:
Error: {result.error}

Execution path: {execution_summary}
Partial data collected: {result.partial_data}

Please explain what happened to the user in a helpful way and suggest alternatives."""

        else:
            prompt = f"""The user asked: "{user_request}"

Here are the results from the specialized agents:
{result.result}

Execution path: {execution_summary}

Please present these results to the user in a clear, helpful format.
Highlight key findings and suggest any follow-up actions they might want to take."""

        response = await chat_agent.run(prompt)
        return response.text

    def get_session_summary(self) -> dict[str, Any]:
        """Get a summary of the current session state.

        :return: Dict with session info
        """
        return {
            "session_id": self._session.id,
            "entries": self._session.keys(),
            "execution_path": self._session.get_path_summary(),
            "total_steps": len(self._session.get_execution_path()),
            "total_duration_ms": self._session.total_duration_ms(),
        }

    def clear_session(self) -> None:
        """Clear the session and start fresh."""
        self._session.clear()
