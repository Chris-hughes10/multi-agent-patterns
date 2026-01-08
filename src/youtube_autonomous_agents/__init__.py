"""YouTube Autonomous Agents - Event-Driven Multi-Agent Patterns.

This module implements the autonomous agent pattern where agents:
- Self-select tasks based on capabilities
- Reason about goals and hand off to each other
- Execute fan-out/fan-in parallel operations
- Complete tasks without central orchestration

Architecture (DDD):
- agents/: Domain layer (agent implementations + base class)
- infra/: Infrastructure layer (registry, pool, queue, routing)
- models/: Shared kernel (task, handoff data structures)
- application/: Application layer (CLI, future API)
"""

from youtube_autonomous_agents.agents.base import BaseAgent
from youtube_autonomous_agents.infra import AgentRegistry
from youtube_autonomous_agents.models import (
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
