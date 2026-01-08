"""Multi-agent coordination patterns.

Available patterns:
- SelfSelectingPool: Event-driven self-selection with autonomous handoffs
"""

from youtube_agent_v2.patterns.self_selection import SelfSelectingPool, run_with_self_selection

__all__ = [
    "SelfSelectingPool",
    "run_with_self_selection",
]
