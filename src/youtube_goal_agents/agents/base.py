"""Base agent abstract class for V2 multi-agent patterns."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent_orchestrator.infra.client import get_chat_client
from youtube_goal_agents.models.task import (
    MaxDepthExceededError,
    Task,
    TaskResult,
    TaskStatus,
)

if TYPE_CHECKING:
    from youtube_goal_agents.infra.registry import AgentRegistry
    from youtube_goal_agents.models.handoff import (
        HandoffResult,
        OperationTimeout,
        PartialResult,
        ValidationResult,
    )

T = TypeVar("T")


class BaseAgent(ABC):
    """Abstract base class for V2 agents.

    Agents are autonomous units that:
    - Declare capabilities they can handle
    - Execute tasks matching those capabilities
    - Can spawn sub-tasks via the registry

    Subclasses must implement:
    - name: Unique agent identifier
    - capabilities: List of capability strings
    - _get_instructions: System prompt for the underlying ChatAgent
    - _get_tools: List of callable tools for the ChatAgent

    :param registry: AgentRegistry for task submission and agent discovery
    :param client: Optional AzureOpenAIChatClient (uses default if not provided)
    """

    # Default timeout for LLM operations (can be overridden per-agent or per-call)
    DEFAULT_LLM_TIMEOUT: float = 30.0

    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,
        llm_timeout: float | None = None,
    ) -> None:
        """Initialize the agent with registry and optional client.

        :param registry: Registry for agent discovery and task submission
        :param client: Optional custom chat client (defaults to shared client)
        :param llm_timeout: Timeout for LLM operations (defaults to DEFAULT_LLM_TIMEOUT)
        """
        self._registry = registry
        self._client = client or get_chat_client()
        self._chat_agent: ChatAgent | None = None
        self._llm_timeout = llm_timeout or self.DEFAULT_LLM_TIMEOUT

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this agent.

        :return: Agent name string
        """
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """List of capabilities this agent can handle.

        Used for task routing - tasks with matching required_capabilities
        will be routed to this agent.

        :return: List of capability strings
        """
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does.

        Used by IntentRouter for semantic matching in autonomous mode.
        Override in subclasses for more specific descriptions.

        :return: Description string
        """
        return f"Agent with capabilities: {', '.join(self.capabilities)}"

    @abstractmethod
    def _get_instructions(self) -> str:
        """Get the system instructions for the underlying ChatAgent.

        :return: System prompt string
        """
        ...

    @abstractmethod
    def _get_tools(self) -> list[Callable[..., Any]]:
        """Get the tools available to this agent.

        :return: List of callable tool functions
        """
        ...

    def can_handle(self, task: Task) -> bool:
        """Check if this agent can handle the given task.

        Routing priority:
        1. LLM-routed tasks: Check if we're the target agent (routed_to field)
        2. Capability-based: Check if our capabilities match required_capabilities

        All tasks should be routed through the LLMIntentRouter (dispatcher pattern).
        Capability-based routing is a fallback for direct task submission.

        :param task: Task to check
        :return: True if agent can handle the task
        """
        # Priority 1: LLM-routed tasks (dispatcher pattern)
        # If the task was routed by LLM, only the target agent can handle it
        routed_to = task.context.get("routed_to")
        if routed_to is not None:
            return routed_to == self.name

        # Priority 2: Capability-based routing (fallback)
        if task.required_capabilities:
            return any(cap in self.capabilities for cap in task.required_capabilities)

        return False

    async def validate_assignment(self, task: Task) -> "ValidationResult":
        """Validate whether this agent should handle the assigned task.

        Called after the dispatcher routes a task to this agent. The agent
        uses LLM reasoning to confirm or reject the assignment.

        Override for custom validation logic.

        :param task: Task that was routed to this agent
        :return: ValidationResult with accepted=True or rejection reason
        """
        from youtube_goal_agents.models.handoff import ValidationResult

        intent = task.context.get("intent", task.description)

        prompt = f"""You are the {self.name} agent. Your role: {self.description}

A task has been routed to you:
INTENT: "{intent}"

Should you handle this task?
- Answer YES if this task matches your capabilities and role
- Answer NO if this task should be handled by a different agent

Respond in this exact format:
DECISION: YES or NO
REASON: Brief explanation (1 sentence)"""

        try:
            response = await self._call_with_timeout_or_raise(
                self._client.get_response(prompt),
                operation="validate_assignment",
                timeout=10.0,  # Quick validation
            )

            response_text = response.text.strip().upper()

            # Parse response
            if "DECISION: YES" in response_text or response_text.startswith("YES"):
                return ValidationResult.accept()
            elif "DECISION: NO" in response_text or response_text.startswith("NO"):
                # Extract reason if present
                reason = f"{self.name} rejected: task doesn't match my role"
                if "REASON:" in response_text:
                    reason_part = response_text.split("REASON:")[-1].strip()
                    if reason_part:
                        reason = reason_part
                return ValidationResult.reject(reason)
            else:
                # Ambiguous response - accept to avoid blocking
                return ValidationResult.accept(confidence=0.5)

        except TimeoutError:
            # On timeout, accept to avoid blocking the workflow
            return ValidationResult.accept(confidence=0.5)

    def _get_chat_agent(self) -> ChatAgent:
        """Get or create the underlying ChatAgent.

        Lazily initializes the ChatAgent on first use.

        :return: Configured ChatAgent instance
        """
        if self._chat_agent is None:
            self._chat_agent = ChatAgent(
                chat_client=self._client,
                name=self.name,
                instructions=self._get_instructions(),
                tools=self._get_tools(),
            )
        return self._chat_agent

    async def _call_with_timeout(
        self,
        coro: Coroutine[Any, Any, T],
        operation: str,
        timeout: float | None = None,
        context: dict[str, Any] | None = None,
        suggested_fallback: str | None = None,
        retryable: bool = True,
    ) -> T | "OperationTimeout":
        """Execute an async operation with timeout, returning context on failure.

        Instead of raising TimeoutError, returns an OperationTimeout object
        that agents can use to reason about the failure and decide how to proceed.

        Example:
            result = await self._call_with_timeout(
                self._client.get_response(prompt),
                operation="goal_reasoning",
                context={"goal": goal},
                suggested_fallback="Use keyword matching instead"
            )
            if isinstance(result, OperationTimeout):
                # Handle timeout - maybe use fallback or hand off
                logger.warning(f"Timeout: {result}")
                return self._fallback_reasoning(goal)

        :param coro: The coroutine to execute
        :param operation: Name/type of operation (for error context)
        :param timeout: Override default timeout (None = use self._llm_timeout)
        :param context: Additional context to include if timeout occurs
        :param suggested_fallback: Hint for how to proceed on timeout
        :param retryable: Whether this operation could be retried
        :return: The coroutine result, or OperationTimeout if timed out
        """
        from youtube_goal_agents.models.handoff import OperationTimeout

        effective_timeout = timeout if timeout is not None else self._llm_timeout

        try:
            return await asyncio.wait_for(coro, timeout=effective_timeout)
        except TimeoutError:
            return OperationTimeout(
                operation=operation,
                timeout_seconds=effective_timeout,
                context=context or {},
                suggested_fallback=suggested_fallback,
                retryable=retryable,
            )

    async def _call_with_timeout_or_raise(
        self,
        coro: Coroutine[Any, Any, T],
        operation: str,
        timeout: float | None = None,
    ) -> T:
        """Execute an async operation with timeout, raising on failure.

        Use this when you want traditional exception behavior rather than
        the OperationTimeout result pattern.

        :param coro: The coroutine to execute
        :param operation: Name/type of operation (for error message)
        :param timeout: Override default timeout (None = use self._llm_timeout)
        :return: The coroutine result
        :raises TimeoutError: If operation times out
        """
        effective_timeout = timeout if timeout is not None else self._llm_timeout

        try:
            return await asyncio.wait_for(coro, timeout=effective_timeout)
        except TimeoutError:
            raise TimeoutError(
                f"{self.name}: {operation} timed out after {effective_timeout}s"
            ) from None

    async def execute(self, task: Task) -> TaskResult:
        """Execute a task and return the result.

        Updates task status during execution. Override this method
        for custom execution logic.

        :param task: Task to execute
        :return: TaskResult with success/failure and data/error
        """
        task.status = TaskStatus.RUNNING

        try:
            chat_agent = self._get_chat_agent()
            result = await chat_agent.run(task.description)

            task.status = TaskStatus.COMPLETED
            return TaskResult(success=True, data=result.text)

        except Exception as e:
            task.status = TaskStatus.FAILED
            return TaskResult(success=False, error=str(e))

    async def execute_autonomous(
        self,
        goal: str,
        state: dict[str, Any],
    ) -> "HandoffResult | PartialResult":
        """Execute autonomously given a goal and accumulated state.

        In autonomous mode, agents receive:
        - goal: The original user request (constant across handoffs)
        - state: Results accumulated from previous agents

        Returns HandoffResult with either:
        - action="complete" + result: Goal is satisfied
        - action="handoff" + intent + state: Need another agent

        Default implementation wraps execute() and returns complete.
        Override for goal-aware reasoning and handoff behavior.

        :param goal: Original user request
        :param state: Accumulated results from previous agents
        :return: HandoffResult or PartialResult on error
        """
        from youtube_goal_agents.models.handoff import HandoffResult, PartialResult

        task = Task(
            description=goal,
            required_capabilities=self.capabilities,
            context=state,
        )
        result = await self.execute(task)

        if result.success:
            return HandoffResult.complete(result.data)
        return PartialResult(error=result.error or "Unknown error", partial_data=state)

    def submit_task(self, task: Task) -> None:
        """Submit a new task to the queue for processing.

        Used for spawning sub-tasks. Validates depth limit before submission.

        :param task: Task to submit
        :raises MaxDepthExceededError: If task depth exceeds max_depth
        """
        if task.current_depth >= task.max_depth:
            raise MaxDepthExceededError(
                f"Task depth {task.current_depth} exceeds max {task.max_depth}"
            )
        self._registry.submit(task)

    async def submit_task_async(self, task: Task) -> None:
        """Submit a new task asynchronously.

        :param task: Task to submit
        :raises MaxDepthExceededError: If task depth exceeds max_depth
        """
        if task.current_depth >= task.max_depth:
            raise MaxDepthExceededError(
                f"Task depth {task.current_depth} exceeds max {task.max_depth}"
            )
        await self._registry.submit_async(task)

    def create_subtask(
        self,
        parent_task: Task,
        description: str,
        required_capabilities: list[str],
        additional_context: dict[str, Any] | None = None,
    ) -> Task:
        """Helper to create a sub-task from a parent task.

        :param parent_task: The parent task
        :param description: What the sub-task should do
        :param required_capabilities: Capabilities needed
        :param additional_context: Extra context to add
        :return: New Task instance
        """
        return parent_task.create_subtask(
            description=description,
            required_capabilities=required_capabilities,
            created_by=self.name,
            additional_context=additional_context,
        )

    def __repr__(self) -> str:
        """String representation of the agent."""
        return f"{self.__class__.__name__}(name={self.name!r}, capabilities={self.capabilities!r})"
