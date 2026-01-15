"""YouTube Goal-Aware Agents - Event-Driven Multi-Agent Patterns.

This module implements the goal-aware agent pattern where agents:
- Validate assigned tasks before execution
- Reason about goals and hand off to each other
- Execute fan-out/fan-in parallel operations
- Coordinate via dispatcher with agent confirmation

Architecture (DDD):
- agents/: Domain layer (agent implementations + base class)
- infra/: Infrastructure layer (registry, pool, queue, routing)
- models/: Shared kernel (task, handoff data structures)
- cli/: CLI layer (commands, driver functions)
"""

from youtube_goal_agents.agents.base import BaseAgent
from youtube_goal_agents.infra import AgentRegistry
from youtube_goal_agents.models import (
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
