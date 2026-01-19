"""Task and TaskResult dataclasses for V2 multi-agent patterns."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class TaskStatus(Enum):
    """Status of a task in the queue."""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskResult:
    """Result of a task execution."""

    success: bool
    data: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        """Validate that failed results have an error message."""
        if not self.success and self.error is None:
            raise ValueError("Failed TaskResult must include an error message")


@dataclass
class Task:
    """A task that can be executed by an agent.

    Tasks flow through the queue and are claimed/assigned to agents.
    They can spawn sub-tasks by incrementing current_depth.

    :param id: Unique task identifier
    :param description: Natural language description of what to do
    :param required_capabilities: List of capabilities needed (e.g., ["search"], ["summarization"])
    :param context: Shared context dict passed between tasks
    :param parent_id: ID of parent task if this is a sub-task
    :param max_depth: Maximum delegation depth to prevent infinite loops
    :param current_depth: Current depth in the task chain
    :param status: Current task status
    :param result: Result after execution completes
    :param created_by: Name of agent that spawned this task
    """

    description: str
    required_capabilities: list[str]
    id: str = field(default_factory=lambda: str(uuid4()))
    context: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    max_depth: int = 5
    current_depth: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None
    created_by: str | None = None

    def create_subtask(
        self,
        description: str,
        required_capabilities: list[str],
        created_by: str,
        additional_context: dict[str, Any] | None = None,
    ) -> "Task":
        """Create a sub-task with inherited context and incremented depth.

        :param description: What the sub-task should do
        :param required_capabilities: Capabilities needed for the sub-task
        :param created_by: Name of the agent creating this sub-task
        :param additional_context: Extra context to merge with parent context
        :return: New Task instance
        :raises MaxDepthExceededError: If current_depth >= max_depth
        """
        if self.current_depth >= self.max_depth:
            raise MaxDepthExceededError(
                f"Task depth {self.current_depth} exceeds max {self.max_depth}"
            )

        merged_context = {**self.context}
        if additional_context:
            merged_context.update(additional_context)

        return Task(
            description=description,
            required_capabilities=required_capabilities,
            context=merged_context,
            parent_id=self.id,
            max_depth=self.max_depth,
            current_depth=self.current_depth + 1,
            created_by=created_by,
        )


class MaxDepthExceededError(Exception):
    """Raised when a task exceeds the maximum delegation depth."""

    pass
