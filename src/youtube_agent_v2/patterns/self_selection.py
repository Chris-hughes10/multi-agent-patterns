"""Self-selection pattern - Agents autonomously claim tasks from queue."""

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from youtube_agent_v2.core import Task, TaskResult, TaskStatus

if TYPE_CHECKING:
    from youtube_agent_v2.core.base_agent import BaseAgent
    from youtube_agent_v2.core.registry import AgentRegistry

logger = logging.getLogger("youtube_agent_v2.self_selection")


class SelfSelectingPool:
    """Pool where agents autonomously watch and claim tasks.

    The self-selection pattern provides decentralized task assignment:
    1. Each agent runs its own watcher coroutine
    2. Agents peek at the queue for unclaimed tasks
    3. Agents compete to claim tasks they can handle
    4. First agent to claim a task executes it

    This pattern is good for:
    - Scalable systems with many agents
    - Natural load balancing (busy agents claim fewer tasks)
    - Autonomous agent behavior
    - Easy addition of new agent types

    :param registry: AgentRegistry with registered agents
    """

    def __init__(self, registry: "AgentRegistry") -> None:
        """Initialize pool with an agent registry.

        :param registry: Registry containing agents and task queue
        """
        self._registry = registry
        self._agent_watchers: dict[str, asyncio.Task[None]] = {}
        self._results: dict[str, TaskResult] = {}
        self._shutdown = asyncio.Event()
        self._poll_interval: float = 0.05  # 50ms between polls

    async def start(self) -> None:
        """Start all agent watchers.

        Creates a watcher coroutine for each registered agent.
        """
        logger.info("Starting self-selecting pool with %d agents", len(self._registry))

        for agent in self._registry.all_agents():
            watcher = asyncio.create_task(
                self._agent_watcher(agent),
                name=f"watcher-{agent.name}",
            )
            self._agent_watchers[agent.name] = watcher
            logger.debug("Started watcher for agent '%s'", agent.name)

    async def _agent_watcher(self, agent: "BaseAgent") -> None:
        """Watch queue and claim tasks this agent can handle.

        Each agent runs this loop independently, competing with
        other agents to claim tasks.

        :param agent: The agent watching for tasks
        """
        logger.debug("Agent '%s' watcher started", agent.name)

        while not self._shutdown.is_set():
            # Peek at next unclaimed task
            task = await self._registry.peek_next_task()

            if task is None:
                # No tasks available, wait and retry
                await asyncio.sleep(self._poll_interval)
                continue

            # Check if we can handle this task
            if not agent.can_handle(task):
                # Not for us, let others try
                await asyncio.sleep(self._poll_interval)
                continue

            # Try to claim the task (atomic operation)
            claimed = await self._registry.try_claim(task.id, agent.name)

            if not claimed:
                # Another agent got it first
                logger.debug(
                    "Agent '%s' failed to claim task %s (already claimed)",
                    agent.name,
                    task.id[:8],
                )
                continue

            # We claimed it - execute
            logger.info("Agent '%s' claimed task %s", agent.name, task.id[:8])
            await self._execute_task(agent, task)

        logger.debug("Agent '%s' watcher stopped", agent.name)

    async def _execute_task(self, agent: "BaseAgent", task: Task) -> None:
        """Execute a claimed task.

        :param agent: Agent executing the task
        :param task: Task to execute
        """
        task.status = TaskStatus.RUNNING

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
            self._results[task.id] = task.result  # type: ignore
            await self._registry.mark_task_completed(task)

    async def submit_and_wait(
        self,
        description: str,
        capabilities: list[str],
        context: dict | None = None,
        timeout: float | None = None,
    ) -> TaskResult:
        """Submit a task and wait for any agent to complete it.

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

        # Wait for any agent to complete it
        completed_task = await self._registry.wait_for_task(task.id, timeout=timeout)

        if completed_task is None:
            return TaskResult(success=False, error="Task timed out")

        return completed_task.result or TaskResult(success=False, error="No result returned")

    async def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shutdown the pool gracefully.

        :param wait: Whether to wait for watchers to stop
        :param timeout: Maximum time to wait
        """
        logger.info("Shutdown requested (wait=%s)", wait)
        self._shutdown.set()

        if wait and self._agent_watchers:
            logger.info("Waiting for %d agent watchers to stop", len(self._agent_watchers))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._agent_watchers.values(), return_exceptions=True),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning("Shutdown timeout - cancelling watchers")
                for watcher in self._agent_watchers.values():
                    watcher.cancel()

    def get_result(self, task_id: str) -> TaskResult | None:
        """Get the result of a completed task.

        :param task_id: Task ID to look up
        :return: TaskResult or None if not found
        """
        return self._results.get(task_id)

    @property
    def is_running(self) -> bool:
        """Check if pool is running."""
        return not self._shutdown.is_set()

    @property
    def active_watcher_count(self) -> int:
        """Get count of active agent watchers."""
        return sum(1 for w in self._agent_watchers.values() if not w.done())


async def run_with_self_selection(
    registry: "AgentRegistry",
    description: str,
    capabilities: list[str],
    context: dict | None = None,
    timeout: float = 60.0,
) -> TaskResult:
    """Convenience function to run a single task with self-selection.

    Creates a pool, runs a single task, and shuts down.

    :param registry: AgentRegistry with registered agents
    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional task context
    :param timeout: Task timeout in seconds
    :return: TaskResult
    """
    pool = SelfSelectingPool(registry)

    # Start the pool
    await pool.start()

    try:
        result = await pool.submit_and_wait(
            description=description,
            capabilities=capabilities,
            context=context,
            timeout=timeout,
        )
        return result

    finally:
        await pool.shutdown(wait=True)
