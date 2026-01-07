"""Handoff types for agent coordination.

Provides structured result types that force explicit completion signaling,
ensuring agents clearly indicate whether they're done or handing off.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class HandoffResult:
    """Result from an agent's execution - either complete or handoff.

    Forces explicit signaling: an agent must either complete with a result,
    or hand off with an intent describing what needs to happen next.

    Example - completing:
        return HandoffResult(
            action="complete",
            result={"videos": [...], "summary": "Found 3 relevant videos"}
        )

    Example - handing off:
        return HandoffResult(
            action="handoff",
            intent="Get transcripts for these videos to find cooking details",
            state={"videos": search_results, "query": original_query}
        )

    :param action: Either "complete" (done) or "handoff" (pass to next agent)
    :param result: The final result (required if action="complete")
    :param intent: Natural language description of what's needed next (required if action="handoff")
    :param state: Accumulated state to pass to the next agent (optional, used with handoff)
    """

    action: Literal["complete", "handoff"]

    # If action == "complete"
    result: Any | None = None

    # If action == "handoff"
    intent: str | None = None
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate that the result is consistent with the action."""
        if self.action == "complete" and self.result is None:
            raise ValueError("Complete action requires a result")
        if self.action == "handoff" and self.intent is None:
            raise ValueError("Handoff action requires an intent")

    @property
    def is_complete(self) -> bool:
        """Check if this result represents completion."""
        return self.action == "complete"

    @property
    def is_handoff(self) -> bool:
        """Check if this result represents a handoff."""
        return self.action == "handoff"

    @classmethod
    def complete(cls, result: Any) -> "HandoffResult":
        """Factory method for creating a completion result.

        :param result: The final result data
        :return: HandoffResult with action="complete"
        """
        return cls(action="complete", result=result)

    @classmethod
    def handoff(
        cls,
        intent: str,
        state: dict[str, Any] | None = None,
    ) -> "HandoffResult":
        """Factory method for creating a handoff result.

        :param intent: Description of what needs to happen next
        :param state: Accumulated state to pass forward
        :return: HandoffResult with action="handoff"
        """
        return cls(action="handoff", intent=intent, state=state or {})


@dataclass
class AgentReasoning:
    """Result of an agent reasoning about a task.

    Used in autonomous mode where agents decide whether they can
    complete, contribute, or need to hand off.

    :param can_complete: Agent can fully satisfy the goal
    :param can_contribute: Agent can do useful work toward the goal
    :param next_intent: If contributing but not completing, what's needed next
    :param reasoning: Optional explanation of the agent's thinking
    """

    can_complete: bool
    can_contribute: bool
    next_intent: str | None = None
    reasoning: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentReasoning":
        """Create from a dictionary (e.g., parsed from LLM JSON response).

        :param data: Dict with can_complete, can_contribute, next_intent keys
        :return: AgentReasoning instance
        """
        return cls(
            can_complete=bool(data.get("can_complete", False)),
            can_contribute=bool(data.get("can_contribute", False)),
            next_intent=data.get("next_intent"),
            reasoning=data.get("reasoning"),
        )


@dataclass
class PartialResult:
    """Result returned when execution cannot complete fully.

    Used when errors occur or loops are detected, providing
    whatever partial data was collected.

    :param error: Description of what went wrong
    :param partial_data: Any data collected before the failure
    :param completed_steps: List of steps that completed successfully
    """

    error: str
    partial_data: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        """Always True for PartialResult."""
        return True
