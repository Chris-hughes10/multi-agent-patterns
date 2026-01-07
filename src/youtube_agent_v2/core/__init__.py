"""Core abstractions for V2 multi-agent patterns.

Structure:
- models/: Pure data structures (Task, HandoffResult, etc.)
- base_agent.py: BaseAgent ABC
- registry.py: AgentRegistry for agent discovery
- session.py: Session state management
- task_queue.py: AsyncTaskQueue
- intent_router.py: Intent-to-agent routing
- loop_detector.py: Cycle detection for autonomous mode
"""

from youtube_agent_v2.core.base_agent import BaseAgent
from youtube_agent_v2.core.intent_router import (
    CapabilityIntentRouter,
    CompositeIntentRouter,
    IntentRouter,
    LLMIntentRouter,
    get_default_router,
)
from youtube_agent_v2.core.loop_detector import AdaptiveLoopDetector, LoopDetector
from youtube_agent_v2.core.models import (
    AgentReasoning,
    HandoffResult,
    MaxDepthExceededError,
    PartialResult,
    Task,
    TaskResult,
    TaskStatus,
)
from youtube_agent_v2.core.registry import AgentRegistry
from youtube_agent_v2.core.session import ExecutionStep, Session, SessionEntry
from youtube_agent_v2.core.task_queue import AsyncTaskQueue

__all__ = [
    # Infrastructure
    "AsyncTaskQueue",
    "BaseAgent",
    "AgentRegistry",
    # Session
    "Session",
    "SessionEntry",
    "ExecutionStep",
    # Routing
    "IntentRouter",
    "LLMIntentRouter",
    "CapabilityIntentRouter",
    "CompositeIntentRouter",
    "get_default_router",
    # Loop detection
    "LoopDetector",
    "AdaptiveLoopDetector",
    # Models (re-exported from models/)
    "Task",
    "TaskResult",
    "TaskStatus",
    "MaxDepthExceededError",
    "HandoffResult",
    "AgentReasoning",
    "PartialResult",
]
