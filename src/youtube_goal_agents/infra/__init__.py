"""Infrastructure layer for youtube_goal_agents.

Contains coordination infrastructure that enables the dispatcher agent pattern:
- AgentRegistry: Agent lookup and capability routing
- TaskQueue: Async task management
- DispatcherPool: LLM-routed agent coordination with validation
- Session: Request-scoped context management
- IntentRouter: LLM-based task routing
- LoopDetector: Circular reference prevention
"""

from youtube_goal_agents.infra.intent_router import IntentRouter
from youtube_goal_agents.infra.loop_detector import LoopDetector
from youtube_goal_agents.infra.pool import DispatcherPool, TaskGroup
from youtube_goal_agents.infra.registry import AgentRegistry
from youtube_goal_agents.infra.session import Session
from youtube_goal_agents.infra.task_queue import AsyncTaskQueue

__all__ = [
    # Core infrastructure
    "AgentRegistry",
    "AsyncTaskQueue",
    "DispatcherPool",
    "TaskGroup",
    "Session",
    # Routing
    "IntentRouter",
    # Safety
    "LoopDetector",
]
