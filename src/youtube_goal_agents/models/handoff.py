"""Handoff types for agent coordination.

Provides structured result types that force explicit completion signaling,
ensuring agents clearly indicate whether they're done or handing off.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class HandoffResult:
    """Result from an agent's execution - complete, handoff, or fan_out.

    Forces explicit signaling: an agent must either complete with a result,
    hand off to a single next agent, or fan out to multiple parallel agents.

    Example - completing:
        return HandoffResult.complete({"videos": [...], "summary": "Found 3 videos"})

    Example - handing off (sequential):
        return HandoffResult.handoff(
            intent="Get transcripts for these videos",
            state={"videos": search_results}
        )

    Example - fan out (parallel):
        return HandoffResult.fan_out(
            intents=["Search chuds bbq for pork loin", "Search fork and embers for pork loin"],
            join_intent="Combine search results and get transcripts",
            state={"query": "pork loin kamado"}
        )

    :param action: "complete" (done), "handoff" (sequential), or "fan_out" (parallel)
    :param result: The final result (required if action="complete")
    :param intent: What's needed next (required if action="handoff")
    :param intents: Multiple parallel tasks (required if action="fan_out")
    :param join_intent: What to do after parallel tasks complete (required if action="fan_out")
    :param state: Accumulated state to pass forward
    """

    action: Literal["complete", "handoff", "fan_out"]

    # If action == "complete"
    result: Any | None = None

    # If action == "handoff"
    intent: str | None = None

    # If action == "fan_out"
    intents: list[str] | None = None
    join_intent: str | None = None

    # Shared state for handoff and fan_out
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate that the result is consistent with the action."""
        if self.action == "complete" and self.result is None:
            raise ValueError("Complete action requires a result")
        if self.action == "handoff" and self.intent is None:
            raise ValueError("Handoff action requires an intent")
        if self.action == "fan_out":
            if not self.intents or len(self.intents) < 2:
                raise ValueError("Fan out action requires at least 2 intents")
            if self.join_intent is None:
                raise ValueError("Fan out action requires a join_intent")

    @property
    def is_complete(self) -> bool:
        """Check if this result represents completion."""
        return self.action == "complete"

    @property
    def is_handoff(self) -> bool:
        """Check if this result represents a sequential handoff."""
        return self.action == "handoff"

    @property
    def is_fan_out(self) -> bool:
        """Check if this result represents parallel fan-out."""
        return self.action == "fan_out"

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
        """Factory method for creating a sequential handoff result.

        :param intent: Description of what needs to happen next
        :param state: Accumulated state to pass forward
        :return: HandoffResult with action="handoff"
        """
        return cls(action="handoff", intent=intent, state=state or {})

    @classmethod
    def fan_out(
        cls,
        intents: list[str],
        join_intent: str,
        state: dict[str, Any] | None = None,
    ) -> "HandoffResult":
        """Factory method for creating a parallel fan-out result.

        Use this when multiple independent tasks can run in parallel,
        then need to be joined before continuing.

        :param intents: List of parallel task descriptions (min 2)
        :param join_intent: What to do after all parallel tasks complete
        :param state: Accumulated state to pass to each parallel task
        :return: HandoffResult with action="fan_out"
        """
        return cls(
            action="fan_out",
            intents=intents,
            join_intent=join_intent,
            state=state or {},
        )


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


@dataclass
class ValidationResult:
    """Result of agent validating whether it can handle an assigned task.

    Used in the dispatcher pattern where agents confirm or reject
    assignments made by the LLMIntentRouter.

    Example - accepting:
        return ValidationResult.accept()

    Example - rejecting:
        return ValidationResult.reject(
            "I handle transcript fetching, not summarization"
        )

    :param accepted: Whether the agent accepts the assignment
    :param rejection_reason: Why the agent rejected (if rejected)
    :param confidence: Agent's confidence in handling this task (0.0-1.0)
    """

    accepted: bool
    rejection_reason: str | None = None
    confidence: float = 1.0

    @classmethod
    def accept(cls, confidence: float = 1.0) -> "ValidationResult":
        """Factory method for accepting an assignment.

        :param confidence: How confident the agent is (0.0-1.0)
        :return: ValidationResult with accepted=True
        """
        return cls(accepted=True, confidence=confidence)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        """Factory method for rejecting an assignment.

        :param reason: Why the agent is rejecting this task
        :return: ValidationResult with accepted=False
        """
        return cls(accepted=False, rejection_reason=reason, confidence=0.0)


@dataclass
class OperationTimeout:
    """Context for a timed-out operation, enabling agents to reason about failures.

    Instead of just raising TimeoutError, this provides structured context
    that agents can use to decide how to proceed (retry, skip, use fallback, etc.).

    Example usage in an agent:
        result = await self._call_with_timeout(
            self._client.get_response(prompt),
            timeout=30.0,
            operation="goal_reasoning",
            context={"goal": goal, "partial_analysis": partial}
        )
        if isinstance(result, OperationTimeout):
            # Agent can reason about the timeout and decide next steps
            return HandoffResult.handoff(
                intent=result.suggested_fallback or "Continue with partial results",
                state={**state, "timeout_context": result.to_dict()}
            )

    :param operation: Name/type of the operation that timed out
    :param timeout_seconds: How long we waited before timing out
    :param context: Any relevant context available at timeout (inputs, partial results)
    :param suggested_fallback: Optional suggestion for how to proceed
    :param retryable: Whether this operation could reasonably be retried
    """

    operation: str
    timeout_seconds: float
    context: dict[str, Any] = field(default_factory=dict)
    suggested_fallback: str | None = None
    retryable: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for state passing.

        :return: Dict representation suitable for JSON serialization
        """
        return {
            "operation": self.operation,
            "timeout_seconds": self.timeout_seconds,
            "context": self.context,
            "suggested_fallback": self.suggested_fallback,
            "retryable": self.retryable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperationTimeout":
        """Create from dictionary.

        :param data: Dict with operation, timeout_seconds, etc.
        :return: OperationTimeout instance
        """
        return cls(
            operation=data.get("operation", "unknown"),
            timeout_seconds=data.get("timeout_seconds", 0.0),
            context=data.get("context", {}),
            suggested_fallback=data.get("suggested_fallback"),
            retryable=data.get("retryable", True),
        )

    def __str__(self) -> str:
        """Human-readable description of the timeout."""
        msg = f"Operation '{self.operation}' timed out after {self.timeout_seconds}s"
        if self.suggested_fallback:
            msg += f". Suggested: {self.suggested_fallback}"
        return msg


@dataclass
class RequestAnalysis:
    """Result of analyzing a user request for parallelism.

    Used by the Synthesizer to determine whether a request contains
    independent tasks that can be executed in parallel.

    :param has_parallelism: Whether the request contains parallel tasks
    :param parallel_intents: List of parallel task descriptions (if parallel)
    :param join_intent: What to do after parallel tasks (if parallel)
    :param first_intent: The first/only task to do (if sequential)
    """

    has_parallelism: bool
    parallel_intents: list[str] = field(default_factory=list)
    join_intent: str | None = None
    first_intent: str | None = None

    @classmethod
    def sequential(cls, intent: str) -> "RequestAnalysis":
        """Create analysis for a sequential (non-parallel) request."""
        return cls(has_parallelism=False, first_intent=intent)

    @classmethod
    def parallel(cls, intents: list[str], join_intent: str) -> "RequestAnalysis":
        """Create analysis for a parallel request."""
        return cls(
            has_parallelism=True,
            parallel_intents=intents,
            join_intent=join_intent,
        )
