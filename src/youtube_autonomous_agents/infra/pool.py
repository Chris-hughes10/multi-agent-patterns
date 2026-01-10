"""Self-selection pattern - Agents autonomously claim tasks from queue.

This pattern combines event-driven task notification with autonomous agent
handoffs. Agents wait for queue notifications (zero CPU when idle), claim
tasks they can handle, execute with goal reasoning, and post handoffs back
to the queue for chaining.

Supports parallel fan-out/fan-in:
- Any agent can return HandoffResult.fan_out() with multiple intents
- Pool tracks task groups and posts join task when all complete
- Enables decentralized parallel execution without central coordination
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from youtube_autonomous_agents.infra.intent_router import LLMIntentRouter
from youtube_autonomous_agents.models import Task, TaskResult, TaskStatus
from youtube_autonomous_agents.models.handoff import HandoffResult

if TYPE_CHECKING:
    from youtube_autonomous_agents.agents.base import BaseAgent
    from youtube_autonomous_agents.infra.registry import AgentRegistry

logger = logging.getLogger("youtube_autonomous_agents.self_selection")


@dataclass
class TaskGroup:
    """Tracks a group of parallel tasks for fan-out/fan-in.

    :param id: Unique group identifier
    :param task_ids: IDs of tasks in this group
    :param join_intent: What to do when all tasks complete
    :param state: Shared state to pass to join task
    :param results: Collected results from completed tasks
    :param parent_task_id: ID of task that triggered the fan-out
    :param join_task_id: ID of the join task (set when posted)
    :param _join_posted: Event signaled when join task is posted (internal)
    """

    id: str
    task_ids: list[str]
    join_intent: str
    state: dict[str, Any]
    parent_task_id: str
    results: dict[str, Any] = field(default_factory=dict)  # task_id -> result
    errors: list[str] = field(default_factory=list)
    join_task_id: str | None = field(default=None)
    _join_posted: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def is_complete(self) -> bool:
        """Check if all tasks in group have completed."""
        return len(self.results) + len(self.errors) >= len(self.task_ids)

    @property
    def collected_results(self) -> list[Any]:
        """Get results as a list (order not guaranteed)."""
        return list(self.results.values())

    def signal_join_posted(self, join_task_id: str) -> None:
        """Signal that the join task has been posted.

        :param join_task_id: ID of the posted join task
        """
        self.join_task_id = join_task_id
        self._join_posted.set()

    async def wait_for_join(self, timeout: float | None = None) -> str | None:
        """Wait for the join task to be posted.

        :param timeout: Max time to wait in seconds
        :return: Join task ID, or None if timeout
        """
        try:
            await asyncio.wait_for(self._join_posted.wait(), timeout=timeout)
            return self.join_task_id
        except TimeoutError:
            return None


class SelfSelectingPool:
    """Pool where agents autonomously watch and claim tasks.

    The self-selection pattern provides decentralized task assignment:
    1. Each agent runs its own watcher coroutine
    2. Agents wait for queue notifications (event-driven, zero CPU when idle)
    3. Agents compete to claim tasks they can handle
    4. First agent to claim a task executes it
    5. If agent returns a handoff, a new task is posted to the queue

    This pattern is good for:
    - Scalable systems with many agents
    - Natural load balancing (busy agents claim fewer tasks)
    - Autonomous agent behavior with goal reasoning
    - Chained handoffs via queue

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
        self._watcher_timeout: float = 0.5  # Timeout for event wait (allows shutdown checks)
        self._intent_router = LLMIntentRouter()  # For intelligent handoff routing

        # Fan-out/fan-in tracking
        self._task_groups: dict[str, TaskGroup] = {}  # group_id -> TaskGroup
        self._task_to_group: dict[str, str] = {}  # task_id -> group_id
        self._groups_lock = asyncio.Lock()  # Protect group state

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
        other agents to claim tasks. Uses event-driven waiting
        instead of polling for zero CPU usage when idle.

        :param agent: The agent watching for tasks
        """
        logger.debug("Agent '%s' watcher started (event-driven)", agent.name)

        # Track tasks we've seen but can't handle (avoid busy loop)
        declined_tasks: set[str] = set()

        while not self._shutdown.is_set():
            # Wait for task notification (event-driven, no polling)
            has_task = await self._registry.wait_for_task_available(
                timeout=self._watcher_timeout
            )

            if not has_task:
                # Timeout - check shutdown and continue waiting
                continue

            # Peek at next unclaimed task
            task = await self._registry.peek_next_task()

            if task is None:
                # Task was claimed by another agent between notification and peek
                logger.debug("Agent '%s' found no unclaimed task after notification", agent.name)
                # Clear declined set when queue is empty - tasks may have changed
                declined_tasks.clear()
                continue

            # Skip tasks we've already declined (avoid busy loop)
            if task.id in declined_tasks:
                # Wait for queue state change before re-checking
                await self._registry.wait_for_queue_change(timeout=self._watcher_timeout)
                continue

            # Check if we can handle this task
            if not agent.can_handle(task):
                # Not for us - mark declined and wait for state change
                logger.debug(
                    "Agent '%s' cannot handle task %s (intent: %s)",
                    agent.name,
                    task.id[:8],
                    task.context.get("intent", "no intent")[:30] if task.context else "no context",
                )
                declined_tasks.add(task.id)
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
                # Clear declined since state changed - other tasks may be available
                declined_tasks.clear()
                continue

            # We claimed it - execute
            logger.info("Agent '%s' claimed task %s", agent.name, task.id[:8])
            # Clear declined after claiming - state is changing
            declined_tasks.clear()
            await self._execute_task(agent, task)

        logger.debug("Agent '%s' watcher stopped", agent.name)

    async def _execute_task(self, agent: "BaseAgent", task: Task) -> None:
        """Execute a claimed task.

        Handles three types of HandoffResult:
        - handoff: Sequential handoff to next agent
        - fan_out: Parallel execution of multiple tasks
        - complete: Task finished

        :param agent: Agent executing the task
        :param task: Task to execute
        """
        task.status = TaskStatus.RUNNING

        try:
            logger.debug("Agent '%s' starting task %s", agent.name, task.id[:8])

            # Try execute_autonomous first if available, fall back to execute
            if hasattr(agent, "execute_autonomous"):
                goal = task.context.get("goal", task.description)
                state = task.context.get("state", {})
                result = await agent.execute_autonomous(goal, state)

                # Handle handoff result
                if isinstance(result, HandoffResult):
                    if result.is_fan_out:
                        # Fan-out: create parallel tasks
                        logger.info(
                            "Agent '%s' fanning out to %d parallel tasks",
                            agent.name,
                            len(result.intents or []),
                        )
                        await self._post_fan_out_tasks(result, task)
                        task.status = TaskStatus.COMPLETED
                        task.result = TaskResult(
                            success=True,
                            data={"fan_out": True, "count": len(result.intents or [])},
                        )
                    elif result.is_handoff:
                        logger.info(
                            "Agent '%s' handing off: %s",
                            agent.name,
                            result.intent[:50] if result.intent else "no intent",
                        )
                        await self._post_handoff_task(result, task)
                        task.status = TaskStatus.COMPLETED
                        task.result = TaskResult(
                            success=True,
                            data={"handoff": True, "intent": result.intent},
                        )
                    else:
                        # Complete - done
                        task.status = TaskStatus.COMPLETED
                        task.result = TaskResult(success=True, data=result.result)
                        logger.info(
                            "Task %s completed by '%s'",
                            task.id[:8],
                            agent.name,
                        )
                else:
                    # PartialResult or other - treat as complete with result
                    task.status = TaskStatus.COMPLETED
                    task.result = TaskResult(
                        success=not getattr(result, "error", None),
                        data=getattr(result, "partial_data", result),
                        error=getattr(result, "error", None),
                    )
            else:
                # Fall back to regular execute
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

            # Check if this task is part of a group
            await self._check_group_completion(task)

    async def _post_handoff_task(
        self,
        result: HandoffResult,
        original_task: Task,
    ) -> None:
        """Convert a handoff result to a new task and submit to queue.

        Uses LLM-based intent routing to determine which agent should
        handle the handoff task. This enables intelligent reasoning about
        the next step rather than keyword matching.

        :param result: HandoffResult with intent and state
        :param original_task: The task that triggered the handoff
        """
        intent = result.intent or "Continue processing"

        # Use LLM to determine which agent should handle this intent
        target_agent = await self._intent_router.find_agent_for_intent(
            intent, self._registry
        )

        routed_to = target_agent.name if target_agent else None
        if routed_to:
            logger.info(
                "LLM routed intent to '%s': %s",
                routed_to,
                intent[:50],
            )
        else:
            logger.warning("LLM could not route intent: %s", intent[:50])

        handoff_task = Task(
            id=str(uuid4()),
            description=intent,
            required_capabilities=[],  # Routed by intent, not capabilities
            context={
                **original_task.context,
                "state": result.state,
                "goal": original_task.context.get("goal", original_task.description),
                "intent": intent,
                "routed_to": routed_to,  # LLM-determined target agent
                "parent_task_id": original_task.id,
            },
            parent_id=original_task.id,
        )

        await self._registry.submit_async(handoff_task)
        logger.debug(
            "Posted handoff task %s (from %s): %s -> %s",
            handoff_task.id[:8],
            original_task.id[:8],
            intent[:50],
            routed_to or "unrouted",
        )

    async def _post_fan_out_tasks(
        self,
        result: HandoffResult,
        original_task: Task,
    ) -> None:
        """Create and post parallel tasks for fan-out.

        Creates a TaskGroup to track the parallel tasks and posts each
        intent as a separate task. When all tasks complete, the join
        task will be posted automatically.

        :param result: HandoffResult with intents and join_intent
        :param original_task: The task that triggered the fan-out
        """
        if not result.intents:
            logger.warning("Fan-out called with no intents")
            return

        group_id = str(uuid4())
        task_ids: list[str] = []

        # Create and post each parallel task
        for i, intent in enumerate(result.intents):
            task_id = str(uuid4())
            task_ids.append(task_id)

            # Route each intent to find target agent
            target_agent = await self._intent_router.find_agent_for_intent(
                intent, self._registry
            )
            routed_to = target_agent.name if target_agent else None

            parallel_task = Task(
                id=task_id,
                description=intent,
                required_capabilities=[],
                context={
                    **original_task.context,
                    "state": {
                        **(result.state if result.state else {}),
                        "is_parallel_task": True,  # Signal to agent to complete, not hand off
                    },
                    "goal": intent,  # Each parallel task has its own goal
                    "original_goal": original_task.context.get("goal", original_task.description),
                    "intent": intent,
                    "routed_to": routed_to,
                    "parent_task_id": original_task.id,
                    "parallel_index": i,
                    "group_id": group_id,
                },
                parent_id=original_task.id,
            )

            await self._registry.submit_async(parallel_task)
            logger.debug(
                "Posted parallel task %d/%d: %s -> %s",
                i + 1,
                len(result.intents),
                intent[:40],
                routed_to or "unrouted",
            )

        # Create and store the task group
        group = TaskGroup(
            id=group_id,
            task_ids=task_ids,
            join_intent=result.join_intent or "Continue processing",
            state=result.state,
            parent_task_id=original_task.id,
        )

        async with self._groups_lock:
            self._task_groups[group_id] = group
            for task_id in task_ids:
                self._task_to_group[task_id] = group_id

        logger.info(
            "Created task group %s with %d parallel tasks, join: %s",
            group_id[:8],
            len(task_ids),
            result.join_intent[:40] if result.join_intent else "no join",
        )

    async def _check_group_completion(self, task: Task) -> None:
        """Check if a completed task's group is now complete.

        If the group is complete, posts the join task to continue processing.

        :param task: The task that just completed
        """
        async with self._groups_lock:
            group_id = self._task_to_group.get(task.id)
            if not group_id:
                return  # Task is not part of a group

            group = self._task_groups.get(group_id)
            if not group:
                return  # Group not found (shouldn't happen)

            # Record result or error
            if task.result and task.result.success:
                group.results[task.id] = task.result.data
            else:
                error_msg = task.result.error if task.result else "Unknown error"
                group.errors.append(f"Task {task.id[:8]}: {error_msg}")

            logger.debug(
                "Group %s progress: %d/%d complete",
                group_id[:8],
                len(group.results) + len(group.errors),
                len(group.task_ids),
            )

            # Check if group is complete
            if not group.is_complete:
                return

        # Group is complete - post the join task (outside lock)
        await self._post_join_task(group)

    async def _post_join_task(self, group: TaskGroup) -> None:
        """Post the join task after all parallel tasks complete.

        :param group: The completed task group
        """
        # Route the join intent
        target_agent = await self._intent_router.find_agent_for_intent(
            group.join_intent, self._registry
        )
        routed_to = target_agent.name if target_agent else None

        join_task = Task(
            id=str(uuid4()),
            description=group.join_intent,
            required_capabilities=[],
            context={
                "state": {
                    **group.state,
                    "parallel_results": group.collected_results,
                    "parallel_errors": group.errors if group.errors else None,
                },
                "goal": group.join_intent,
                "intent": group.join_intent,
                "routed_to": routed_to,
                "parent_task_id": group.parent_task_id,
                "from_group": group.id,
            },
            parent_id=group.parent_task_id,
        )

        await self._registry.submit_async(join_task)

        # Signal waiters that join task is ready (event-driven notification)
        group.signal_join_posted(join_task.id)

        logger.info(
            "Posted join task %s for group %s: %s -> %s (results: %d, errors: %d)",
            join_task.id[:8],
            group.id[:8],
            group.join_intent[:40],
            routed_to or "unrouted",
            len(group.results),
            len(group.errors),
        )

        # Clean up the group (but keep reference for waiters to access join_task_id)
        async with self._groups_lock:
            for task_id in group.task_ids:
                self._task_to_group.pop(task_id, None)
            # Note: Don't delete from _task_groups yet - waiters may need it

    async def submit_and_wait(
        self,
        description: str,
        capabilities: list[str],
        context: dict | None = None,
        timeout: float | None = None,
    ) -> TaskResult:
        """Submit a task and wait for the full handoff chain to complete.

        :param description: Natural language task description
        :param capabilities: Required capabilities for the task
        :param context: Optional context dict
        :param timeout: Optional timeout in seconds
        :return: TaskResult when complete (follows handoff chain)
        """
        import time

        start_time = time.time()

        # Ensure goal and intent are set in context for autonomous execution
        task_context = context.copy() if context else {}
        if "goal" not in task_context:
            task_context["goal"] = description
        if "intent" not in task_context:
            task_context["intent"] = description

        task = Task(
            id=str(uuid4()),
            description=description,
            required_capabilities=capabilities,
            context=task_context,
        )

        await self._registry.submit_async(task)
        logger.info("Submitted task %s: %s", task.id[:8], description[:50])

        current_task_id = task.id
        max_handoffs = 10  # Prevent infinite loops

        for _ in range(max_handoffs):
            # Calculate remaining timeout
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = max(0, timeout - elapsed)
                if remaining_timeout <= 0:
                    return TaskResult(success=False, error="Task timed out")

            # Wait for current task to complete
            completed_task = await self._registry.wait_for_task(
                current_task_id, timeout=remaining_timeout
            )

            if completed_task is None:
                return TaskResult(success=False, error="Task timed out")

            result = completed_task.result
            if result is None:
                return TaskResult(success=False, error="No result returned")

            # Check if this was a handoff - if so, follow the chain
            if isinstance(result.data, dict) and result.data.get("handoff"):
                # Find the handoff task by looking for tasks with this parent_id
                handoff_task = await self._find_handoff_task(current_task_id, remaining_timeout)
                if handoff_task:
                    logger.debug(
                        "Following handoff from %s to %s",
                        current_task_id[:8],
                        handoff_task.id[:8],
                    )
                    current_task_id = handoff_task.id
                    continue
                else:
                    # No handoff task found, return what we have
                    return result
            else:
                # Not a handoff, we're done
                return result

        return TaskResult(success=False, error="Max handoffs exceeded")

    async def submit_fan_out_and_wait(
        self,
        intents: list[str],
        join_intent: str,
        context: dict | None = None,
        timeout: float | None = None,
    ) -> TaskResult:
        """Submit parallel tasks and wait for all to complete including join.

        Creates a task group, posts all parallel tasks, waits for completion,
        then follows the join task chain to completion.

        :param intents: List of parallel task descriptions
        :param join_intent: What to do after all parallel tasks complete
        :param context: Optional shared context dict
        :param timeout: Optional timeout in seconds
        :return: TaskResult when complete (after join task)
        """
        import time

        if len(intents) < 2:
            return TaskResult(success=False, error="Fan-out requires at least 2 intents")

        start_time = time.time()
        group_id = str(uuid4())
        task_ids: list[str] = []
        base_context = context.copy() if context else {}

        # Create and post each parallel task
        for i, intent in enumerate(intents):
            task_id = str(uuid4())
            task_ids.append(task_id)

            # Route each intent to find target agent
            target_agent = await self._intent_router.find_agent_for_intent(
                intent, self._registry
            )
            routed_to = target_agent.name if target_agent else None

            parallel_task = Task(
                id=task_id,
                description=intent,
                required_capabilities=[],
                context={
                    **base_context,
                    "state": {
                        "is_parallel_task": True,  # Signal to agent to complete, not hand off
                    },
                    "goal": intent,
                    "original_goal": join_intent,
                    "intent": intent,
                    "routed_to": routed_to,
                    "parallel_index": i,
                    "group_id": group_id,
                },
            )

            await self._registry.submit_async(parallel_task)

        # Create and store the task group
        group = TaskGroup(
            id=group_id,
            task_ids=task_ids,
            join_intent=join_intent,
            state=base_context,
            parent_task_id="",  # No parent for initial fan-out
        )

        async with self._groups_lock:
            self._task_groups[group_id] = group
            for task_id in task_ids:
                self._task_to_group[task_id] = group_id

        logger.info(
            "Submitted fan-out: %d parallel tasks, join: %s",
            len(intents),
            join_intent[:50],
        )

        # Wait for all parallel tasks to complete
        for task_id in task_ids:
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = max(0, timeout - elapsed)
                if remaining_timeout <= 0:
                    return TaskResult(success=False, error="Fan-out timed out")

            await self._registry.wait_for_task(task_id, timeout=remaining_timeout)

        # Find and follow the join task
        remaining_timeout = None
        if timeout:
            elapsed = time.time() - start_time
            remaining_timeout = max(0, timeout - elapsed)

        # Look for the join task (posted by _check_group_completion)
        join_task = await self._find_join_task(group_id, remaining_timeout)
        if not join_task:
            # Group might have completed without join (all errors?)
            async with self._groups_lock:
                if group_id in self._task_groups:
                    grp = self._task_groups[group_id]
                    return TaskResult(
                        success=len(grp.errors) == 0,
                        data={"results": grp.collected_results, "errors": grp.errors},
                        error="; ".join(grp.errors) if grp.errors else None,
                    )
            return TaskResult(success=False, error="Join task not found")

        # Follow the join task chain to completion
        current_task_id = join_task.id
        max_handoffs = 10

        for _ in range(max_handoffs):
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = max(0, timeout - elapsed)
                if remaining_timeout <= 0:
                    return TaskResult(success=False, error="Join chain timed out")

            completed_task = await self._registry.wait_for_task(
                current_task_id, timeout=remaining_timeout
            )

            if completed_task is None:
                return TaskResult(success=False, error="Join task timed out")

            result = completed_task.result
            if result is None:
                return TaskResult(success=False, error="No result from join task")

            # Check if this was a handoff
            if isinstance(result.data, dict) and result.data.get("handoff"):
                handoff_task = await self._find_handoff_task(current_task_id, remaining_timeout)
                if handoff_task:
                    current_task_id = handoff_task.id
                    continue
                return result
            elif isinstance(result.data, dict) and result.data.get("fan_out"):
                # Nested fan-out - follow the join for that group
                nested_group_id = result.data.get("group_id")
                if nested_group_id:
                    nested_join = await self._find_join_task(nested_group_id, remaining_timeout)
                    if nested_join:
                        current_task_id = nested_join.id
                        continue
                return result
            else:
                return result

        return TaskResult(success=False, error="Max handoffs exceeded in join chain")

    async def _find_join_task(
        self,
        group_id: str,
        timeout: float | None = None,
    ) -> Task | None:
        """Find the join task for a completed group (event-driven).

        Uses the TaskGroup's event to wait for join task notification
        instead of polling, resulting in zero CPU usage while waiting.

        :param group_id: ID of the task group
        :param timeout: Max time to wait
        :return: The join task or None
        """
        # Get the group to access its event
        async with self._groups_lock:
            group = self._task_groups.get(group_id)

        if not group:
            # Group not found - try queue scan as fallback
            return await self._scan_queue_for_join_task(group_id)

        # Wait for join task notification (event-driven, no polling)
        join_task_id = await group.wait_for_join(timeout=timeout)

        if not join_task_id:
            return None

        # Retrieve the actual task from the queue
        queue = self._registry.task_queue
        async with queue._lock:
            task = queue._pending.get(join_task_id) or queue._completed.get(join_task_id)

        # Clean up the group now that we've retrieved the join task
        async with self._groups_lock:
            self._task_groups.pop(group_id, None)

        return task

    async def _scan_queue_for_join_task(self, group_id: str) -> Task | None:
        """Fallback: scan queue for join task by group_id.

        Used when the group is not in _task_groups (e.g., already cleaned up).

        :param group_id: ID of the task group
        :return: The join task or None
        """
        queue = self._registry.task_queue
        async with queue._lock:
            for task in queue._pending.values():
                if task.context.get("from_group") == group_id:
                    return task
            for task in queue._completed.values():
                if task.context.get("from_group") == group_id:
                    return task
        return None

    async def _find_handoff_task(
        self,
        parent_task_id: str,
        timeout: float | None = None,
    ) -> Task | None:
        """Find a handoff task by its parent_id.

        :param parent_task_id: ID of the parent task
        :param timeout: Max time to wait for the task to appear
        :return: The handoff task or None
        """
        import time

        start_time = time.time()
        poll_interval = 0.1  # Short poll since task should appear quickly

        while True:
            # Check pending tasks for one with matching parent_id
            task = await self._registry.peek_next_task()
            if task and task.parent_id == parent_task_id:
                return task

            # Also check if it's already being processed (in pending but claimed)
            # by scanning the task queue's pending dict
            queue = self._registry.task_queue
            async with queue._lock:
                for pending_task in queue._pending.values():
                    if pending_task.parent_id == parent_task_id:
                        return pending_task

            # Check timeout
            if timeout and time.time() - start_time >= timeout:
                return None

            await asyncio.sleep(poll_interval)

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
