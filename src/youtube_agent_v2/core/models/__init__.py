"""Data models for V2 multi-agent patterns.

Pure data structures with minimal behavior (validation only).
"""

from youtube_agent_v2.core.models.handoff import (
    AgentReasoning,
    HandoffResult,
    PartialResult,
)
from youtube_agent_v2.core.models.task import (
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
]
