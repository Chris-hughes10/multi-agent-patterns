"""Session state management for multi-turn conversations.

Provides a Session class that stores conversation context across turns,
allowing both Planner and Autonomous approaches to reference previous results.

Also provides ExecutionStep for tracking the execution path through agents.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class ExecutionStep:
    """Record of a single step in the execution path.

    Tracks which agent ran, what action it took, timing information,
    and what state keys it read/wrote. Used for debugging and visualization.

    :param agent_name: Name of the agent that executed
    :param action: What the agent did ("execute", "handoff", "complete", "error")
    :param timestamp: When the step started
    :param task_id: ID of the task being executed
    :param input_state_keys: State keys the agent read from
    :param output_state_keys: State keys the agent wrote to
    :param duration_ms: How long the step took in milliseconds
    :param intent: If handoff, the intent passed to next agent
    :param error: Error message if action="error"
    """

    agent_name: str
    action: str  # "execute", "handoff", "complete", "error"
    timestamp: datetime
    task_id: str
    input_state_keys: list[str] = field(default_factory=list)
    output_state_keys: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    intent: str | None = None
    error: str | None = None

    @classmethod
    def create(
        cls,
        agent_name: str,
        action: str,
        task_id: str,
        input_state_keys: list[str] | None = None,
        output_state_keys: list[str] | None = None,
        duration_ms: float = 0.0,
        intent: str | None = None,
        error: str | None = None,
    ) -> "ExecutionStep":
        """Factory method with automatic timestamp.

        :param agent_name: Name of the agent
        :param action: Action taken
        :param task_id: Task ID
        :param input_state_keys: Keys read from state
        :param output_state_keys: Keys written to state
        :param duration_ms: Execution time
        :param intent: Handoff intent if applicable
        :param error: Error message if applicable
        :return: ExecutionStep instance
        """
        return cls(
            agent_name=agent_name,
            action=action,
            timestamp=datetime.now(),
            task_id=task_id,
            input_state_keys=input_state_keys or [],
            output_state_keys=output_state_keys or [],
            duration_ms=duration_ms,
            intent=intent,
            error=error,
        )


@dataclass
class SessionEntry:
    """A single entry in the session history.

    :param key: Identifier for this entry (e.g., "search", "transcript_abc123")
    :param value: The stored data
    :param timestamp: When this entry was created
    :param metadata: Additional info (agent that created it, task_id, etc.)
    """

    key: str
    value: Any
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class Session:
    """Stateful session for multi-turn agent interactions.

    Stores results from previous turns so agents can reference them.
    Supports both direct key access and path-based lookups like "$search.results[0]".

    Example usage:
        session = Session()
        session.store("search", {"results": [{"video_id": "abc"}, {"video_id": "def"}]})
        session.store("transcript_abc", {"text": "Hello world..."})

        # Direct access
        search_results = session.get("search")

        # Path-based access (for DAG variable resolution)
        video_id = session.resolve("$search.results[0].video_id")  # Returns "abc"
    """

    def __init__(self, session_id: str | None = None) -> None:
        """Initialize a new session.

        :param session_id: Optional ID, auto-generated if not provided
        """
        self.id = session_id or str(uuid4())
        self._entries: dict[str, SessionEntry] = {}
        self._execution_path: list[ExecutionStep] = []
        self.created_at = datetime.now()

    def store(
        self,
        key: str,
        value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a value in the session.

        :param key: Identifier for this entry
        :param value: Data to store
        :param metadata: Optional metadata (agent name, task_id, etc.)
        """
        self._entries[key] = SessionEntry(
            key=key,
            value=value,
            metadata=metadata or {},
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a stored value by key.

        :param key: Entry identifier
        :param default: Value to return if key not found
        :return: Stored value or default
        """
        entry = self._entries.get(key)
        return entry.value if entry else default

    def get_entry(self, key: str) -> SessionEntry | None:
        """Get the full entry including metadata.

        :param key: Entry identifier
        :return: SessionEntry or None
        """
        return self._entries.get(key)

    def has(self, key: str) -> bool:
        """Check if a key exists in the session.

        :param key: Entry identifier
        :return: True if key exists
        """
        return key in self._entries

    def keys(self) -> list[str]:
        """Get all stored keys.

        :return: List of key names
        """
        return list(self._entries.keys())

    def resolve(self, path: str) -> Any:
        """Resolve a variable path like "$search.results[0].video_id".

        Path format:
        - Must start with "$"
        - First segment is the session key
        - Subsequent segments are attribute/index access
        - Supports both dot notation (.field) and bracket notation ([0], ["key"])

        :param path: Variable path string
        :return: Resolved value
        :raises ValueError: If path is invalid or key not found
        :raises KeyError: If path segment not found in data
        :raises IndexError: If array index out of bounds
        """
        if not path.startswith("$"):
            raise ValueError(f"Path must start with '$': {path}")

        # Remove $ prefix
        path = path[1:]

        # Parse the path into segments
        segments = self._parse_path(path)
        if not segments:
            raise ValueError(f"Empty path after '$'")

        # First segment is the session key
        key = segments[0]
        if not self.has(key):
            raise KeyError(f"Session key not found: {key}")

        value = self.get(key)

        # Navigate through remaining segments
        for segment in segments[1:]:
            if isinstance(segment, int):
                # Array index
                value = value[segment]
            else:
                # Dict key or object attribute
                if isinstance(value, dict):
                    value = value[segment]
                else:
                    value = getattr(value, segment)

        return value

    def _parse_path(self, path: str) -> list[str | int]:
        """Parse a path string into segments.

        Examples:
            "search.results[0].video_id" -> ["search", "results", 0, "video_id"]
            "transcript_abc.text" -> ["transcript_abc", "text"]

        :param path: Path string (without $ prefix)
        :return: List of path segments (strings for keys, ints for indices)
        """
        segments: list[str | int] = []
        current = ""
        i = 0

        while i < len(path):
            char = path[i]

            if char == ".":
                # End current segment, start new one
                if current:
                    segments.append(current)
                    current = ""
                i += 1

            elif char == "[":
                # End current segment if any
                if current:
                    segments.append(current)
                    current = ""

                # Find closing bracket
                end = path.find("]", i)
                if end == -1:
                    raise ValueError(f"Unclosed bracket in path: {path}")

                index_str = path[i + 1 : end]

                # Check if it's a number or a quoted string
                if index_str.isdigit():
                    segments.append(int(index_str))
                elif index_str.startswith('"') and index_str.endswith('"'):
                    segments.append(index_str[1:-1])
                elif index_str.startswith("'") and index_str.endswith("'"):
                    segments.append(index_str[1:-1])
                else:
                    # Treat as string key
                    segments.append(index_str)

                i = end + 1

            else:
                current += char
                i += 1

        # Don't forget the last segment
        if current:
            segments.append(current)

        return segments

    def to_dict(self) -> dict[str, Any]:
        """Export session state as a dictionary.

        Useful for serialization or passing to agents.

        :return: Dict of key -> value pairs
        """
        return {key: entry.value for key, entry in self._entries.items()}

    def clear(self) -> None:
        """Clear all session entries and execution path."""
        self._entries.clear()
        self._execution_path.clear()

    # -------------------------------------------------------------------------
    # Execution Path Tracking
    # -------------------------------------------------------------------------

    def record_step(self, step: ExecutionStep) -> None:
        """Record an execution step in the path.

        :param step: The execution step to record
        """
        self._execution_path.append(step)

    def get_execution_path(self) -> list[ExecutionStep]:
        """Get the full execution path for debugging/visualization.

        :return: Copy of the execution path list
        """
        return self._execution_path.copy()

    def get_path_summary(self) -> str:
        """Get a human-readable execution summary.

        :return: String like "search(execute) → transcript(handoff) → summarize(complete)"
        """
        if not self._execution_path:
            return "(empty)"
        return " → ".join(
            f"{step.agent_name}({step.action})" for step in self._execution_path
        )

    def get_last_step(self) -> ExecutionStep | None:
        """Get the most recent execution step.

        :return: Last ExecutionStep or None if path is empty
        """
        return self._execution_path[-1] if self._execution_path else None

    def get_steps_by_agent(self, agent_name: str) -> list[ExecutionStep]:
        """Get all steps executed by a specific agent.

        :param agent_name: Name of the agent
        :return: List of ExecutionSteps from that agent
        """
        return [s for s in self._execution_path if s.agent_name == agent_name]

    def get_agent_visit_counts(self) -> dict[str, int]:
        """Get a count of how many times each agent was visited.

        Useful for loop detection.

        :return: Dict mapping agent_name -> visit count
        """
        counts: dict[str, int] = {}
        for step in self._execution_path:
            counts[step.agent_name] = counts.get(step.agent_name, 0) + 1
        return counts

    def total_duration_ms(self) -> float:
        """Get total execution time across all steps.

        :return: Sum of duration_ms for all steps
        """
        return sum(step.duration_ms for step in self._execution_path)

    def __len__(self) -> int:
        """Return number of entries in session."""
        return len(self._entries)

    def __repr__(self) -> str:
        """String representation."""
        return f"Session(id={self.id!r}, entries={list(self._entries.keys())})"
