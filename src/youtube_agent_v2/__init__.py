"""YouTube Agent V2 - Multi-Agent Patterns.

This module explores two multi-agent patterns beyond the V1 orchestrator approach:
1. Queue + Dispatcher - Central dispatcher assigns tasks from queue
2. Queue + Self-Selection - Agents claim tasks based on capabilities
"""

from youtube_agent_v2.core import (
    AgentRegistry,
    BaseAgent,
    HandoffResult,
    Task,
    TaskResult,
    TaskStatus,
)

__all__ = [
    "AgentRegistry",
    "BaseAgent",
    "HandoffResult",
    "Task",
    "TaskResult",
    "TaskStatus",
]
