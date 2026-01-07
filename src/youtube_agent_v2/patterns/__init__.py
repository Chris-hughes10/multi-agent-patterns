"""Multi-agent coordination patterns.

Available patterns:
- Dispatcher: Central coordinator assigns tasks to agents
- SelfSelection: Agents autonomously claim tasks from queue
"""

from youtube_agent_v2.patterns.dispatcher import DispatcherCoordinator, run_with_dispatcher
from youtube_agent_v2.patterns.self_selection import SelfSelectingPool, run_with_self_selection

__all__ = [
    "DispatcherCoordinator",
    "SelfSelectingPool",
    "run_with_dispatcher",
    "run_with_self_selection",
]
