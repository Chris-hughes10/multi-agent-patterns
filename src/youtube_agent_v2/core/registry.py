"""Agent registry for discovery and task routing."""

from typing import TYPE_CHECKING

from youtube_agent_v2.core.models.task import Task
from youtube_agent_v2.core.task_queue import AsyncTaskQueue

if TYPE_CHECKING:
    from youtube_agent_v2.core.base_agent import BaseAgent


class AgentRegistry:
    """Registry for agent discovery and task routing.

    Maintains an index of agents by their capabilities, enabling
    efficient lookup of which agents can handle a given task.

    :ivar _agents: Dict of agent_name -> BaseAgent
    :ivar _capabilities_index: Dict of capability -> list[agent_name]
    :ivar _task_queue: Shared task queue for all agents
    """

    def __init__(self) -> None:
        """Initialize an empty registry with a task queue."""
        self._agents: dict[str, BaseAgent] = {}
        self._capabilities_index: dict[str, list[str]] = {}
        self._task_queue = AsyncTaskQueue()

    def register(self, agent: "BaseAgent") -> None:
        """Register an agent and index its capabilities.

        :param agent: Agent to register
        :raises ValueError: If agent with same name already registered
        """
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' is already registered")

        self._agents[agent.name] = agent

        # Index capabilities for fast lookup
        for capability in agent.capabilities:
            if capability not in self._capabilities_index:
                self._capabilities_index[capability] = []
            self._capabilities_index[capability].append(agent.name)

    def unregister(self, agent_name: str) -> None:
        """Remove an agent from the registry.

        :param agent_name: Name of agent to remove
        :raises KeyError: If agent not found
        """
        if agent_name not in self._agents:
            raise KeyError(f"Agent '{agent_name}' not found in registry")

        agent = self._agents[agent_name]

        # Remove from capabilities index
        for capability in agent.capabilities:
            if capability in self._capabilities_index:
                self._capabilities_index[capability] = [
                    name for name in self._capabilities_index[capability] if name != agent_name
                ]
                # Clean up empty capability lists
                if not self._capabilities_index[capability]:
                    del self._capabilities_index[capability]

        del self._agents[agent_name]

    def get_agent(self, name: str) -> "BaseAgent":
        """Get an agent by name.

        :param name: Agent name
        :return: The agent
        :raises KeyError: If agent not found
        """
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found in registry")
        return self._agents[name]

    def find_agents_for_task(self, task: Task) -> list["BaseAgent"]:
        """Find all agents capable of handling a task.

        Looks up agents that have at least one of the required capabilities.

        :param task: Task to find agents for
        :return: List of capable agents (may be empty)
        """
        candidate_names: set[str] = set()

        for capability in task.required_capabilities:
            agent_names = self._capabilities_index.get(capability, [])
            candidate_names.update(agent_names)

        return [self._agents[name] for name in candidate_names]

    def find_agents_by_capability(self, capability: str) -> list["BaseAgent"]:
        """Find all agents with a specific capability.

        :param capability: Capability to search for
        :return: List of agents with that capability
        """
        agent_names = self._capabilities_index.get(capability, [])
        return [self._agents[name] for name in agent_names]

    def all_agents(self) -> list["BaseAgent"]:
        """Get all registered agents.

        :return: List of all agents
        """
        return list(self._agents.values())

    def all_capabilities(self) -> list[str]:
        """Get all registered capabilities.

        :return: List of all capability names
        """
        return list(self._capabilities_index.keys())

    # Task queue delegation methods

    def submit(self, task: Task) -> None:
        """Submit a task to the queue (sync wrapper).

        For async submission, access the queue directly via task_queue property.

        :param task: Task to submit
        """
        import asyncio

        # Handle both sync and async contexts
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._task_queue.put(task))
        except RuntimeError:
            # No running loop - create one for the put operation
            asyncio.run(self._task_queue.put(task))

    async def submit_async(self, task: Task) -> None:
        """Submit a task to the queue asynchronously.

        :param task: Task to submit
        """
        await self._task_queue.put(task)

    async def get_next_task(self) -> Task:
        """Get the next task from queue (async, blocking).

        :return: Next available task
        """
        return await self._task_queue.get()

    async def peek_next_task(self) -> Task | None:
        """Peek at the next unclaimed task.

        :return: Next unclaimed task or None
        """
        return await self._task_queue.peek()

    async def try_claim(self, task_id: str, agent_name: str) -> bool:
        """Try to claim a task for an agent.

        :param task_id: Task ID to claim
        :param agent_name: Agent claiming the task
        :return: True if claim succeeded
        """
        return await self._task_queue.try_claim(task_id, agent_name)

    async def mark_task_completed(self, task: Task) -> None:
        """Mark a task as completed.

        :param task: Completed task
        """
        await self._task_queue.mark_completed(task)

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> Task | None:
        """Wait for a task to complete.

        :param task_id: Task ID to wait for
        :param timeout: Optional timeout in seconds
        :return: Completed task or None on timeout
        """
        return await self._task_queue.wait_for_task(task_id, timeout)

    @property
    def task_queue(self) -> AsyncTaskQueue:
        """Access the underlying task queue.

        :return: The AsyncTaskQueue instance
        """
        return self._task_queue

    def __len__(self) -> int:
        """Get the number of registered agents."""
        return len(self._agents)

    def __contains__(self, agent_name: str) -> bool:
        """Check if an agent is registered."""
        return agent_name in self._agents
