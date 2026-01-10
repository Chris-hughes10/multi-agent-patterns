"""Base agent abstract class for V2 multi-agent patterns."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent_orchestrator.infra.client import get_chat_client
from youtube_autonomous_agents.models.task import (
    MaxDepthExceededError,
    Task,
    TaskResult,
    TaskStatus,
)

if TYPE_CHECKING:
    from youtube_autonomous_agents.infra.registry import AgentRegistry
    from youtube_autonomous_agents.models.handoff import (
        HandoffResult,
        OperationTimeout,
        PartialResult,
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
        3. Intent-based fallback: Use keyword matching (legacy)

        :param task: Task to check
        :return: True if agent can handle the task
        """
        # Priority 1: LLM-routed handoff tasks
        # If the task was routed by LLM, only the target agent can handle it
        routed_to = task.context.get("routed_to")
        if routed_to is not None:
            return routed_to == self.name

        # Priority 2: Capability-based routing
        if task.required_capabilities:
            return any(cap in self.capabilities for cap in task.required_capabilities)

        # Priority 3: Intent-based fallback (for unrouted handoffs)
        intent = task.context.get("intent", "")
        if intent:
            return self._can_handle_intent(intent)

        return False

    def _can_handle_intent(self, intent: str) -> bool:
        """Check if this agent can handle a natural language intent.

        Uses keyword matching against capabilities and description.
        Override for more sophisticated intent matching.

        :param intent: Natural language intent from handoff
        :return: True if this agent should handle the intent
        """
        intent_lower = intent.lower()

        # Map common intent keywords to capabilities
        intent_keywords = {
            "transcript": ["transcript", "captions", "spoken words", "text from video"],
            "summarize": ["summarize", "summary", "key points", "extract", "analyze"],
            "search": ["search", "find videos", "look for"],
            "write": ["write", "save", "export", "file"],
        }

        for capability in self.capabilities:
            # Direct capability match
            if capability.replace("_", " ") in intent_lower:
                return True

            # Check capability-specific keywords
            cap_base = capability.split("_")[0]  # e.g., "youtube_search" -> "youtube"
            if cap_base in intent_keywords and any(
                kw in intent_lower for kw in intent_keywords[cap_base]
            ):
                return True

        # Also check against agent name
        return self.name in intent_lower

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
        from youtube_autonomous_agents.models.handoff import OperationTimeout

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
        from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult

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
