"""Async task queue with support for peek and claim operations."""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_agent_v2.core.models.task import Task


class AsyncTaskQueue:
    """Thread-safe async task queue with claim support.

    Supports two modes of operation:
    1. Simple get/put for dispatcher pattern
    2. Peek/claim for self-selection pattern where agents compete for tasks

    :ivar _queue: Internal asyncio queue for task ordering
    :ivar _pending: Dict of task_id -> Task for quick lookup
    :ivar _claimed: Dict of task_id -> agent_name for tracking claims
    :ivar _completed: Dict of task_id -> Task for completed task lookup
    :ivar _lock: Async lock for atomic operations
    """

    def __init__(self) -> None:
        """Initialize an empty task queue."""
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._pending: dict[str, Task] = {}
        self._claimed: dict[str, str] = {}  # task_id -> agent_name
        self._completed: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._task_events: dict[str, asyncio.Event] = {}  # For waiting on specific tasks
        self._new_task_event = asyncio.Event()  # For event-driven notifications

    async def put(self, task: "Task") -> None:
        """Add a task to the queue.

        :param task: Task to add
        """
        async with self._lock:
            self._pending[task.id] = task
            self._task_events[task.id] = asyncio.Event()
        await self._queue.put(task)
        # Wake up any agents waiting for tasks
        self._new_task_event.set()

    async def get(self) -> "Task":
        """Get the next task from the queue (blocking).

        Used by dispatcher pattern - removes task from queue.

        :return: Next available task
        """
        task = await self._queue.get()
        return task

    def get_nowait(self) -> "Task | None":
        """Get the next task without blocking.

        :return: Next task or None if queue is empty
        """
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def peek(self) -> "Task | None":
        """Peek at the next unclaimed task without consuming it.

        Used by self-selection pattern - agents check what's available.

        :return: Next unclaimed task or None
        """
        async with self._lock:
            for task_id, task in self._pending.items():
                if task_id not in self._claimed and task_id not in self._completed:
                    return task
        return None

    async def try_claim(self, task_id: str, agent_name: str) -> bool:
        """Atomically try to claim a task for an agent.

        Used by self-selection pattern - agents compete to claim tasks.

        :param task_id: ID of task to claim
        :param agent_name: Name of agent claiming the task
        :return: True if claim succeeded, False if already claimed or not found
        """
        async with self._lock:
            if task_id in self._claimed:
                return False  # Already claimed by another agent
            if task_id not in self._pending:
                return False  # Task doesn't exist or already completed
            self._claimed[task_id] = agent_name
        # Notify agents waiting for queue changes
        self._new_task_event.set()
        return True

    async def mark_completed(self, task: "Task") -> None:
        """Mark a task as completed and notify waiters.

        :param task: Completed task with result set
        """
        async with self._lock:
            self._completed[task.id] = task
            if task.id in self._pending:
                del self._pending[task.id]
            if task.id in self._claimed:
                del self._claimed[task.id]
            if task.id in self._task_events:
                self._task_events[task.id].set()
        # Notify agents waiting for queue changes
        self._new_task_event.set()

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> "Task | None":
        """Wait for a specific task to complete.

        :param task_id: ID of task to wait for
        :param timeout: Optional timeout in seconds
        :return: Completed task or None if timeout
        """
        event = self._task_events.get(task_id)
        if event is None:
            # Task might already be completed
            return self._completed.get(task_id)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._completed.get(task_id)
        except TimeoutError:
            return None

    def get_pending_count(self) -> int:
        """Get the number of pending (unclaimed) tasks.

        :return: Count of pending tasks
        """
        return len(self._pending) - len(self._claimed)

    def get_claimed_count(self) -> int:
        """Get the number of claimed (in-progress) tasks.

        :return: Count of claimed tasks
        """
        return len(self._claimed)

    def is_empty(self) -> bool:
        """Check if queue has no pending tasks.

        :return: True if no pending tasks
        """
        return self._queue.empty() and len(self._pending) == 0

    async def wait_for_task_available(self, timeout: float | None = None) -> bool:
        """Wait until an unclaimed task is available (event-driven).

        This method blocks until a task is available, avoiding polling.
        Returns immediately if an unclaimed task already exists.

        :param timeout: Optional timeout in seconds
        :return: True if a task is available, False if timeout
        """
        while True:
            # Check if any unclaimed task exists
            async with self._lock:
                for task_id in self._pending:
                    if task_id not in self._claimed:
                        return True

            # No task available, wait for notification
            self._new_task_event.clear()
            try:
                await asyncio.wait_for(self._new_task_event.wait(), timeout=timeout)
            except TimeoutError:
                return False

    async def wait_for_queue_change(self, timeout: float | None = None) -> bool:
        """Wait for any queue state change (new task, claim, or completion).

        Used by agents to wait when they've declined a task, to avoid
        busy looping while waiting for someone else to claim it.

        :param timeout: Optional timeout in seconds
        :return: True if a change occurred, False if timeout
        """
        self._new_task_event.clear()
        try:
            await asyncio.wait_for(self._new_task_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False
