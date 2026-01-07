"""Loop detection for autonomous agent coordination.

Detects cyclic handoff patterns to prevent infinite loops when agents
hand off work to each other.
"""

from youtube_agent_v2.core.session import ExecutionStep


class LoopDetector:
    """Detects cyclic handoff patterns in agent execution.

    Used in the autonomous pattern to detect when agents are stuck in
    a loop (e.g., A → B → A → B → ...). Provides two detection methods:
    1. Visit count: Agent visited too many times in recent history
    2. Cycle detection: Repeated subsequence pattern

    Example:
        detector = LoopDetector(max_visits=2, window_size=10)

        # Check before each handoff
        if detector.check_for_loop(session.get_execution_path()):
            cycle = detector.detect_cycle(session.get_execution_path())
            return PartialResult(error=f"Loop detected: {cycle}")

    :param max_visits: Maximum times an agent can be visited in the window
    :param window_size: Number of recent steps to analyze
    """

    def __init__(self, max_visits: int = 2, window_size: int = 10) -> None:
        """Initialize the loop detector.

        :param max_visits: Max times same agent can appear in window
        :param window_size: Number of recent steps to check
        """
        self._max_visits = max_visits
        self._window_size = window_size

    @property
    def max_visits(self) -> int:
        """Maximum allowed visits per agent in the window."""
        return self._max_visits

    @property
    def window_size(self) -> int:
        """Number of recent steps to analyze."""
        return self._window_size

    def check_for_loop(self, execution_path: list[ExecutionStep]) -> bool:
        """Check if the execution path indicates a loop.

        Looks at recent history (window_size steps) and checks if any
        agent has been visited more than max_visits times.

        :param execution_path: List of execution steps
        :return: True if a loop is detected
        """
        if not execution_path:
            return False

        recent = execution_path[-self._window_size :]
        agent_visits: dict[str, int] = {}

        for step in recent:
            # Count handoffs specifically, as those indicate routing decisions
            if step.action in ("handoff", "execute"):
                agent_visits[step.agent_name] = agent_visits.get(step.agent_name, 0) + 1
                if agent_visits[step.agent_name] > self._max_visits:
                    return True

        return False

    def detect_cycle(self, execution_path: list[ExecutionStep]) -> list[str] | None:
        """Detect the specific cycle pattern if one exists.

        Looks for repeated subsequences in the agent visit order.
        For example, ["search", "transcript", "search", "transcript"]
        would return ["search", "transcript"].

        :param execution_path: List of execution steps
        :return: The repeating cycle pattern, or None if no cycle found
        """
        if len(execution_path) < 4:  # Need at least 4 steps to detect a cycle
            return None

        # Extract recent agent names
        recent = execution_path[-self._window_size :]
        agent_sequence = [s.agent_name for s in recent if s.action in ("handoff", "execute")]

        if len(agent_sequence) < 4:
            return None

        # Look for repeated subsequences of increasing length
        for length in range(2, len(agent_sequence) // 2 + 1):
            pattern = agent_sequence[-length:]
            prev_pattern = agent_sequence[-2 * length : -length]
            if pattern == prev_pattern:
                return pattern

        return None

    def get_visit_counts(self, execution_path: list[ExecutionStep]) -> dict[str, int]:
        """Get visit counts for each agent in the recent window.

        Useful for debugging and understanding execution patterns.

        :param execution_path: List of execution steps
        :return: Dict mapping agent_name -> visit count
        """
        recent = execution_path[-self._window_size :]
        counts: dict[str, int] = {}

        for step in recent:
            if step.action in ("handoff", "execute"):
                counts[step.agent_name] = counts.get(step.agent_name, 0) + 1

        return counts

    def get_recent_sequence(self, execution_path: list[ExecutionStep]) -> list[str]:
        """Get the recent sequence of agent names.

        :param execution_path: List of execution steps
        :return: List of agent names in recent order
        """
        recent = execution_path[-self._window_size :]
        return [s.agent_name for s in recent if s.action in ("handoff", "execute")]

    def suggest_max_steps(self, num_agents: int) -> int:
        """Suggest a reasonable max_steps based on number of agents.

        For N agents, a reasonable workflow might visit each agent
        once or twice, so suggest N * max_visits as a guideline.

        :param num_agents: Number of agents in the system
        :return: Suggested maximum steps
        """
        return num_agents * self._max_visits


class AdaptiveLoopDetector(LoopDetector):
    """Loop detector that adapts thresholds based on observed patterns.

    Starts with default thresholds but can relax them if legitimate
    multi-visit patterns are detected (e.g., search → transcript →
    search for next video → transcript).

    :param max_visits: Initial maximum visits per agent
    :param window_size: Number of recent steps to analyze
    :param allowed_revisit_agents: Agents allowed to be revisited more often
    """

    def __init__(
        self,
        max_visits: int = 2,
        window_size: int = 10,
        allowed_revisit_agents: list[str] | None = None,
    ) -> None:
        """Initialize the adaptive loop detector.

        :param max_visits: Initial max visits per agent
        :param window_size: Number of recent steps to check
        :param allowed_revisit_agents: Agents with relaxed visit limits
        """
        super().__init__(max_visits, window_size)
        self._allowed_revisit_agents = set(allowed_revisit_agents or [])
        self._revisit_multiplier = 2  # Allowed agents get 2x the visit limit

    def add_allowed_revisit_agent(self, agent_name: str) -> None:
        """Mark an agent as allowed to be revisited more often.

        :param agent_name: Agent name to allow more visits
        """
        self._allowed_revisit_agents.add(agent_name)

    def check_for_loop(self, execution_path: list[ExecutionStep]) -> bool:
        """Check for loops with adaptive thresholds.

        Agents in allowed_revisit_agents get a higher visit limit.

        :param execution_path: List of execution steps
        :return: True if a loop is detected
        """
        if not execution_path:
            return False

        recent = execution_path[-self._window_size :]
        agent_visits: dict[str, int] = {}

        for step in recent:
            if step.action in ("handoff", "execute"):
                agent_visits[step.agent_name] = agent_visits.get(step.agent_name, 0) + 1

                # Determine the limit for this agent
                limit = self._max_visits
                if step.agent_name in self._allowed_revisit_agents:
                    limit = self._max_visits * self._revisit_multiplier

                if agent_visits[step.agent_name] > limit:
                    return True

        return False
