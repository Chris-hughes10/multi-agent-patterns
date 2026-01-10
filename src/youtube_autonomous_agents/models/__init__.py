"""Data models for V2 multi-agent patterns.

Pure data structures with minimal behavior (validation only).
"""

from youtube_autonomous_agents.models.handoff import (
    AgentReasoning,
    HandoffResult,
    OperationTimeout,
    PartialResult,
)
from youtube_autonomous_agents.models.task import (
    MaxDepthExceededError,
    Task,
    TaskResult,
    TaskStatus,
)

__all__ = [
    # Task models
    "Task",
    "TaskResult",
    "TaskStatus",
    "MaxDepthExceededError",
    # Handoff models
    "HandoffResult",
    "AgentReasoning",
    "PartialResult",
    "OperationTimeout",
]
