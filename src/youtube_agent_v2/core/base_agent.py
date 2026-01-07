"""Base agent abstract class for V2 multi-agent patterns."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent.infra.client import get_chat_client
from youtube_agent_v2.core.models.task import MaxDepthExceededError, Task, TaskResult, TaskStatus

if TYPE_CHECKING:
    from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult
    from youtube_agent_v2.core.registry import AgentRegistry


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

    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,
    ) -> None:
        """Initialize the agent with registry and optional client.

        :param registry: Registry for agent discovery and task submission
        :param client: Optional custom chat client (defaults to shared client)
        """
        self._registry = registry
        self._client = client or get_chat_client()
        self._chat_agent: ChatAgent | None = None

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

        Returns True if any of the agent's capabilities match
        any of the task's required capabilities.

        :param task: Task to check
        :return: True if agent can handle the task
        """
        return any(cap in self.capabilities for cap in task.required_capabilities)

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
        from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult

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
