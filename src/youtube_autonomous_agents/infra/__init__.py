"""Infrastructure layer for youtube_autonomous_agents.

Contains coordination infrastructure that enables the autonomous agent pattern:
- AgentRegistry: Agent lookup and capability routing
- TaskQueue: Async task management
- SelfSelectingPool: Event-driven agent coordination
- Session: Request-scoped context management
- IntentRouter: LLM-based task routing
- LoopDetector: Circular reference prevention
"""

from youtube_autonomous_agents.infra.intent_router import IntentRouter
from youtube_autonomous_agents.infra.loop_detector import LoopDetector
from youtube_autonomous_agents.infra.pool import SelfSelectingPool, TaskGroup
from youtube_autonomous_agents.infra.registry import AgentRegistry
from youtube_autonomous_agents.infra.session import Session
from youtube_autonomous_agents.infra.task_queue import AsyncTaskQueue

__all__ = [
    # Core infrastructure
    "AgentRegistry",
    "AsyncTaskQueue",
    "SelfSelectingPool",
    "TaskGroup",
    "Session",
    # Routing
    "IntentRouter",
    # Safety
    "LoopDetector",
]
