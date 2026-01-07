"""Dispatcher pattern - Central coordinator assigns tasks to agents."""

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from youtube_agent_v2.core import Task, TaskResult, TaskStatus

if TYPE_CHECKING:
    from youtube_agent_v2.core.base_agent import BaseAgent
    from youtube_agent_v2.core.registry import AgentRegistry

logger = logging.getLogger("youtube_agent_v2.dispatcher")


class DispatcherCoordinator:
    """Central dispatcher that assigns tasks from queue to agents.

    The dispatcher pattern provides centralized control over task assignment:
    1. User submits a task via submit_and_wait()
    2. Dispatcher pulls tasks from queue in run() loop
    3. Finds capable agents via registry
    4. Assigns task to first capable agent
    5. Executes concurrently up to max_concurrent limit

    This pattern is good for:
    - Controlled parallel execution
    - Centralized logging/monitoring
    - Simple agent selection logic

    :param registry: AgentRegistry with registered agents
    """

    def __init__(self, registry: "AgentRegistry") -> None:
        """Initialize dispatcher with an agent registry.

        :param registry: Registry containing agents and task queue
        """
        self._registry = registry
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._results: dict[str, TaskResult] = {}
        self._shutdown = asyncio.Event()
        self._semaphore: asyncio.Semaphore | None = None

    async def submit_and_wait(
        self,
        description: str,
        capabilities: list[str],
        context: dict | None = None,
        timeout: float | None = None,
    ) -> TaskResult:
        """Submit a task and wait for its completion.

        Convenience method for single-task workflows.

        :param description: Natural language task description
        :param capabilities: Required capabilities for the task
        :param context: Optional context dict
        :param timeout: Optional timeout in seconds
        :return: TaskResult when complete
        """
        task = Task(
            id=str(uuid4()),
            description=description,
            required_capabilities=capabilities,
            context=context or {},
        )

        await self._registry.submit_async(task)
        logger.info("Submitted task %s: %s", task.id[:8], description[:50])

        # Wait for completion
        completed_task = await self._registry.wait_for_task(task.id, timeout=timeout)

        if completed_task is None:
            return TaskResult(success=False, error="Task timed out")

        return completed_task.result or TaskResult(success=False, error="No result returned")

    async def run(self, max_concurrent: int = 3) -> None:
        """Main dispatch loop - runs until shutdown.

        Continuously pulls tasks from queue and assigns to capable agents.
        Respects max_concurrent limit for parallel execution.

        :param max_concurrent: Maximum concurrent task executions
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        logger.info("Dispatcher started with max_concurrent=%d", max_concurrent)

        while not self._shutdown.is_set():
            try:
                # Wait for next task with timeout to check shutdown
                task = await asyncio.wait_for(
                    self._registry.get_next_task(),
                    timeout=0.5,
                )
            except TimeoutError:
                continue

            # Find capable agents
            agents = self._registry.find_agents_for_task(task)

            if not agents:
                logger.warning("No capable agent for task %s: %s", task.id[:8], task.description)
                task.status = TaskStatus.FAILED
                task.result = TaskResult(
                    success=False,
                    error=f"No agent found with capabilities: {task.required_capabilities}",
                )
                await self._registry.mark_task_completed(task)
                continue

            # Select agent (simple strategy: first match)
            agent = self._select_agent(agents, task)
            logger.info(
                "Assigning task %s to agent '%s'",
                task.id[:8],
                agent.name,
            )

            # Execute with concurrency limit
            asyncio.create_task(self._execute_with_semaphore(agent, task))

        logger.info("Dispatcher shutting down")

    def _select_agent(self, agents: list["BaseAgent"], task: Task) -> "BaseAgent":  # noqa: ARG002
        """Select which agent should handle a task.

        Override this method for custom selection strategies
        (e.g., load balancing, priority, specialization score).

        :param agents: List of capable agents
        :param task: Task to assign
        :return: Selected agent
        """
        # Default: first capable agent
        return agents[0]

    async def _execute_with_semaphore(self, agent: "BaseAgent", task: Task) -> None:
        """Execute task with semaphore for concurrency control.

        :param agent: Agent to execute task
        :param task: Task to execute
        """
        if self._semaphore is None:
            raise RuntimeError("Dispatcher not started - call run() first")

        async with self._semaphore:
            await self._execute_task(agent, task)

    async def _execute_task(self, agent: "BaseAgent", task: Task) -> None:
        """Execute a task with an agent.

        :param agent: Agent to execute task
        :param task: Task to execute
        """
        task.status = TaskStatus.RUNNING
        task_key = f"{agent.name}:{task.id}"
        self._running_tasks[task_key] = asyncio.current_task()  # type: ignore

        try:
            logger.debug("Agent '%s' starting task %s", agent.name, task.id[:8])
            result = await agent.execute(task)
            task.status = TaskStatus.COMPLETED
            task.result = result
            logger.info(
                "Task %s completed by '%s': success=%s",
                task.id[:8],
                agent.name,
                result.success,
            )

        except Exception as e:
            logger.error("Task %s failed: %s", task.id[:8], e)
            task.status = TaskStatus.FAILED
            task.result = TaskResult(success=False, error=str(e))

        finally:
            self._running_tasks.pop(task_key, None)
            self._results[task.id] = task.result  # type: ignore
            await self._registry.mark_task_completed(task)

    async def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shutdown the dispatcher gracefully.

        :param wait: Whether to wait for running tasks to complete
        :param timeout: Maximum time to wait for tasks
        """
        logger.info("Shutdown requested (wait=%s)", wait)
        self._shutdown.set()

        if wait and self._running_tasks:
            logger.info("Waiting for %d running tasks", len(self._running_tasks))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._running_tasks.values(), return_exceptions=True),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning("Shutdown timeout - some tasks may be incomplete")

    def get_result(self, task_id: str) -> TaskResult | None:
        """Get the result of a completed task.

        :param task_id: Task ID to look up
        :return: TaskResult or None if not found
        """
        return self._results.get(task_id)

    @property
    def is_running(self) -> bool:
        """Check if dispatcher is running."""
        return not self._shutdown.is_set()

    @property
    def active_task_count(self) -> int:
        """Get count of currently executing tasks."""
        return len(self._running_tasks)


async def run_with_dispatcher(
    registry: "AgentRegistry",
    description: str,
    capabilities: list[str],
    context: dict | None = None,
    timeout: float = 60.0,
) -> TaskResult:
    """Convenience function to run a single task with dispatcher.

    Creates a dispatcher, runs a single task, and shuts down.

    :param registry: AgentRegistry with registered agents
    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional task context
    :param timeout: Task timeout in seconds
    :return: TaskResult
    """
    dispatcher = DispatcherCoordinator(registry)

    # Start dispatcher in background
    dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=3))

    try:
        result = await dispatcher.submit_and_wait(
            description=description,
            capabilities=capabilities,
            context=context,
            timeout=timeout,
        )
        return result

    finally:
        await dispatcher.shutdown(wait=True)
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task
