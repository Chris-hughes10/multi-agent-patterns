"""Intent routing for agent selection.

Provides an abstraction for routing natural language intents to capable agents.
Start with LLM-based routing, but the interface allows swapping to embedding-based
or keyword-based approaches later.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent.infra.client import get_chat_client

if TYPE_CHECKING:
    from youtube_agent_v2.core.base_agent import BaseAgent
    from youtube_agent_v2.core.registry import AgentRegistry


class IntentRouter(ABC):
    """Abstract interface for routing intents to agents.

    Intent routing is used in the autonomous pattern where agents hand off
    work using natural language descriptions rather than capability strings.

    Example:
        router = LLMIntentRouter()
        agent = await router.find_agent_for_intent(
            "Get the spoken words from this YouTube video",
            registry
        )
        # Returns TranscriptAgent
    """

    @abstractmethod
    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry",
    ) -> "BaseAgent | None":
        """Find the best agent to handle the given intent.

        :param intent: Natural language description of what needs to be done
        :param registry: Agent registry to search
        :return: Best matching agent, or None if no suitable agent found
        """
        ...


class LLMIntentRouter(IntentRouter):
    """Routes intents using LLM evaluation.

    For each agent, asks the LLM whether the agent can handle the intent.
    Simple but potentially expensive for many agents.

    :param client: Optional chat client (uses default if not provided)
    :param confidence_threshold: Minimum confidence (0-1) to accept a match
    """

    def __init__(
        self,
        client: AzureOpenAIChatClient | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        """Initialize the router.

        :param client: Optional chat client for LLM calls
        :param confidence_threshold: Minimum confidence to accept a match
        """
        self._client = client or get_chat_client()
        self._confidence_threshold = confidence_threshold

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry",
    ) -> "BaseAgent | None":
        """Find agent by asking LLM to evaluate each candidate.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :return: Best matching agent or None
        """
        best_agent: BaseAgent | None = None
        best_score = 0.0

        for agent in registry.all_agents():
            score = await self._evaluate_agent(agent, intent)
            if score > best_score and score >= self._confidence_threshold:
                best_score = score
                best_agent = agent

        return best_agent

    async def _evaluate_agent(self, agent: "BaseAgent", intent: str) -> float:
        """Evaluate how well an agent matches an intent.

        :param agent: Agent to evaluate
        :param intent: Intent to match against
        :return: Confidence score 0-1
        """
        # Get agent description (use capabilities as fallback)
        description = getattr(agent, "description", None)
        if description is None:
            description = f"Agent with capabilities: {', '.join(agent.capabilities)}"

        prompt = f"""You are evaluating whether an agent can handle a task.

AGENT: {agent.name}
DESCRIPTION: {description}
CAPABILITIES: {', '.join(agent.capabilities)}

TASK INTENT: "{intent}"

On a scale of 0.0 to 1.0, how well can this agent handle this task?
- 1.0 = Perfect match, this is exactly what the agent does
- 0.7+ = Good match, agent can definitely help
- 0.5 = Partial match, agent might be able to help
- Below 0.5 = Poor match, agent is not suitable

Respond with ONLY a number between 0.0 and 1.0, nothing else."""

        try:
            response = await self._client.create(messages=[{"role": "user", "content": prompt}])
            score_text = response.content.strip()
            return float(score_text)
        except (ValueError, AttributeError):
            # If we can't parse the response, return 0
            return 0.0


class CapabilityIntentRouter(IntentRouter):
    """Routes intents by matching keywords to capabilities.

    Fast routing based on keyword overlap between intent and agent capabilities.
    Falls back to another router if no clear match is found.

    :param fallback: Optional router to use when keyword matching is ambiguous
    """

    def __init__(self, fallback: IntentRouter | None = None) -> None:
        """Initialize with optional fallback router.

        :param fallback: Router to use when keyword matching fails
        """
        self._fallback = fallback
        # Map common keywords to capabilities
        self._keyword_map: dict[str, list[str]] = {
            # Search-related
            "search": ["youtube_search", "search", "video_discovery"],
            "find": ["youtube_search", "search", "video_discovery"],
            "look for": ["youtube_search", "search"],
            "discover": ["youtube_search", "video_discovery"],
            # Transcript-related
            "transcript": ["transcript_fetch", "transcript", "transcript_storage"],
            "captions": ["transcript_fetch", "transcript"],
            "subtitles": ["transcript_fetch", "transcript"],
            "spoken words": ["transcript_fetch", "transcript"],
            "what was said": ["transcript_fetch", "transcript"],
            # Summarization-related
            "summarize": ["summarization", "summarize", "text_analysis"],
            "summary": ["summarization", "summarize"],
            "key points": ["summarization", "text_analysis"],
            "main ideas": ["summarization", "text_analysis"],
            "analyze": ["summarization", "text_analysis"],
            # Writing-related
            "write": ["file_export", "markdown_writing", "write"],
            "export": ["file_export", "markdown_writing"],
            "save": ["file_export", "markdown_writing", "transcript_storage"],
            "markdown": ["markdown_writing"],
            "file": ["file_export", "markdown_writing"],
        }

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry",
    ) -> "BaseAgent | None":
        """Find agent by matching keywords in intent to capabilities.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :return: Best matching agent or None
        """
        intent_lower = intent.lower()
        matched_capabilities: set[str] = set()

        # Find all capabilities that match keywords in the intent
        for keyword, capabilities in self._keyword_map.items():
            if keyword in intent_lower:
                matched_capabilities.update(capabilities)

        if not matched_capabilities:
            # No keyword matches - use fallback if available
            if self._fallback:
                return await self._fallback.find_agent_for_intent(intent, registry)
            return None

        # Find agents that have any of the matched capabilities
        candidates: list[tuple[BaseAgent, int]] = []
        for agent in registry.all_agents():
            overlap = len(set(agent.capabilities) & matched_capabilities)
            if overlap > 0:
                candidates.append((agent, overlap))

        if not candidates:
            if self._fallback:
                return await self._fallback.find_agent_for_intent(intent, registry)
            return None

        # If exactly one candidate or clear winner, return it
        candidates.sort(key=lambda x: x[1], reverse=True)

        if len(candidates) == 1:
            return candidates[0][0]

        # Multiple candidates with same score - use fallback for disambiguation
        if candidates[0][1] == candidates[1][1] and self._fallback:
            return await self._fallback.find_agent_for_intent(intent, registry)

        # Return best match
        return candidates[0][0]


class CompositeIntentRouter(IntentRouter):
    """Combines multiple routers with a chain-of-responsibility pattern.

    Tries each router in order until one returns a result.

    :param routers: List of routers to try in order
    """

    def __init__(self, routers: list[IntentRouter]) -> None:
        """Initialize with list of routers.

        :param routers: Routers to try in order
        """
        if not routers:
            raise ValueError("CompositeIntentRouter requires at least one router")
        self._routers = routers

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry",
    ) -> "BaseAgent | None":
        """Try each router until one finds a match.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :return: First matching agent found, or None
        """
        for router in self._routers:
            agent = await router.find_agent_for_intent(intent, registry)
            if agent is not None:
                return agent
        return None


def get_default_router() -> IntentRouter:
    """Get the default intent router configuration.

    Returns a CapabilityIntentRouter with LLMIntentRouter as fallback.
    This provides fast keyword-based routing with LLM disambiguation
    for ambiguous cases.

    :return: Configured IntentRouter
    """
    llm_router = LLMIntentRouter()
    return CapabilityIntentRouter(fallback=llm_router)
