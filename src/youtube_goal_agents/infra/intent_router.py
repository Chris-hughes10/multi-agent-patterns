"""Intent routing for agent selection.

Provides an abstraction for routing natural language intents to capable agents.
Start with LLM-based routing, but the interface allows swapping to embedding-based
or keyword-based approaches later.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent_orchestrator.infra.client import get_chat_client

if TYPE_CHECKING:
    from youtube_goal_agents.agents.base import BaseAgent
    from youtube_goal_agents.infra.registry import AgentRegistry


INTENT_ROUTING_PROMPT = """You are a task router for a multi-agent workflow. Route the intent to the FIRST agent needed.

AVAILABLE AGENTS:
{agents_text}

INTENT TO ROUTE: "{intent}"
{rejection_context}
Instructions:
1. If the intent has MULTIPLE steps (e.g., "get transcripts AND summarize"), choose the FIRST step
2. The workflow order is typically: search → transcript → summarize → writer
3. Agent selection rules:
   - If we need to FIND/SEARCH for videos → "search"
   - If we need to GET/FETCH transcripts or captions → "transcript"
   - If we already HAVE transcripts/text and need to analyze/summarize/extract → "summarize"
   - If we need to SAVE/WRITE/EXPORT to a file → "writer"
4. Key: "Get transcripts and then summarize" → choose "transcript" (first step)
5. Key: "Summarize these transcripts" (transcripts already provided) → choose "summarize"
6. Respond with ONLY the agent name (e.g., "search", "transcript", "summarize", "writer")
7. If no agent can help, respond with "none"

Agent name:"""


class IntentRouter(ABC):
    """Abstract interface for routing intents to agents.

    Intent routing is used in the dispatcher pattern where agents hand off
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
        excluded_agents: list[str] | None = None,
        rejection_context: str | None = None,
    ) -> "BaseAgent | None":
        """Find the best agent to handle the given intent.

        :param intent: Natural language description of what needs to be done
        :param registry: Agent registry to search
        :param excluded_agents: Agent names to exclude from consideration (e.g., agents that rejected)
        :param rejection_context: Context about why previous routing failed (helps LLM make better choice)
        :return: Best matching agent, or None if no suitable agent found
        """
        ...


class LLMIntentRouter(IntentRouter):
    """Routes intents using LLM evaluation.

    For multi-step intents, asks the LLM to identify the FIRST step
    and which agent should handle it. This enables the autonomous
    chain to start at the right place.

    :param client: Optional chat client (uses default if not provided)
    """

    def __init__(
        self,
        client: AzureOpenAIChatClient | None = None,
    ) -> None:
        """Initialize the router.

        :param client: Optional chat client for LLM calls
        """
        self._client = client or get_chat_client()

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry",
        excluded_agents: list[str] | None = None,
        rejection_context: str | None = None,
    ) -> "BaseAgent | None":
        """Find agent by asking LLM which agent should handle FIRST.

        For multi-step intents, identifies the first step in the workflow
        and returns the agent best suited to handle it.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :param excluded_agents: Agent names to exclude (e.g., agents that rejected this task)
        :param rejection_context: Why previous routing failed (helps LLM choose better)
        :return: Best matching agent for the first step, or None
        """
        # Build agent catalog for the prompt, excluding rejected agents
        all_agents = registry.all_agents()
        excluded_set = set(excluded_agents or [])
        agents = [a for a in all_agents if a.name not in excluded_set]

        if not agents:
            return None

        agent_descriptions = []
        for agent in agents:
            desc = getattr(agent, "description", f"Agent with capabilities: {', '.join(agent.capabilities)}")
            agent_descriptions.append(f"- {agent.name}: {desc}")

        agents_text = "\n".join(agent_descriptions)

        # Build rejection context section if provided
        rejection_text = ""
        if rejection_context:
            rejection_text = f"\nPREVIOUS ROUTING FAILED: {rejection_context}\nChoose a different agent that can handle this.\n"

        prompt = INTENT_ROUTING_PROMPT.format(
            agents_text=agents_text,
            intent=intent,
            rejection_context=rejection_text,
        )

        try:
            response = await self._client.get_response(prompt)
            agent_name = response.text.strip().lower()

            # Handle "none" response
            if agent_name == "none":
                return None

            # Find the agent by name
            for agent in agents:
                if agent.name.lower() == agent_name:
                    return agent

            # If exact match failed, try partial match
            for agent in agents:
                if agent_name in agent.name.lower() or agent.name.lower() in agent_name:
                    return agent

            return None

        except (ValueError, AttributeError):
            return None


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
            # Search-related - explicit search terms
            "search": ["youtube_search", "search", "video_discovery"],
            "find": ["youtube_search", "search", "video_discovery"],
            "look for": ["youtube_search", "search"],
            "discover": ["youtube_search", "video_discovery"],
            # Search-related - natural language phrases
            "videos about": ["youtube_search", "video_discovery"],
            "videos on": ["youtube_search", "video_discovery"],
            "youtube": ["youtube_search", "video_discovery"],
            "on youtube": ["youtube_search", "video_discovery"],
            "from youtube": ["youtube_search", "video_discovery"],
            "based on": ["youtube_search", "video_discovery"],
            "info on": ["youtube_search", "video_discovery"],
            "information about": ["youtube_search", "video_discovery"],
            "how to": ["youtube_search", "video_discovery", "summarization"],
            "techniques": ["youtube_search", "video_discovery"],
            "tutorial": ["youtube_search", "video_discovery"],
            "learn about": ["youtube_search", "video_discovery"],
            "channels": ["youtube_search", "video_discovery"],
            # Transcript-related
            "transcript": ["transcript_fetch", "transcript", "transcript_storage"],
            "captions": ["transcript_fetch", "transcript"],
            "subtitles": ["transcript_fetch", "transcript"],
            "spoken words": ["transcript_fetch", "transcript"],
            "what was said": ["transcript_fetch", "transcript"],
            "words from": ["transcript_fetch", "transcript"],
            # Summarization-related
            "summarize": ["summarization", "summarize", "text_analysis"],
            "summary": ["summarization", "summarize"],
            "key points": ["summarization", "text_analysis"],
            "main ideas": ["summarization", "text_analysis"],
            "analyze": ["summarization", "text_analysis"],
            "extract": ["summarization", "text_analysis"],
            "tell me about": ["summarization", "text_analysis"],
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
        excluded_agents: list[str] | None = None,
        rejection_context: str | None = None,
    ) -> "BaseAgent | None":
        """Find agent by matching keywords in intent to capabilities.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :param excluded_agents: Agent names to exclude from consideration
        :param rejection_context: Context about why previous routing failed (passed to fallback)
        :return: Best matching agent or None
        """
        intent_lower = intent.lower()
        matched_capabilities: set[str] = set()
        excluded_set = set(excluded_agents or [])

        # Find all capabilities that match keywords in the intent
        for keyword, capabilities in self._keyword_map.items():
            if keyword in intent_lower:
                matched_capabilities.update(capabilities)

        if not matched_capabilities:
            # No keyword matches - use fallback if available
            if self._fallback:
                return await self._fallback.find_agent_for_intent(
                    intent, registry, excluded_agents, rejection_context
                )
            return None

        # Find agents that have any of the matched capabilities (excluding rejected agents)
        candidates: list[tuple["BaseAgent", int]] = []
        for agent in registry.all_agents():
            if agent.name in excluded_set:
                continue
            overlap = len(set(agent.capabilities) & matched_capabilities)
            if overlap > 0:
                candidates.append((agent, overlap))

        if not candidates:
            if self._fallback:
                return await self._fallback.find_agent_for_intent(
                    intent, registry, excluded_agents, rejection_context
                )
            return None

        # If exactly one candidate or clear winner, return it
        candidates.sort(key=lambda x: x[1], reverse=True)

        if len(candidates) == 1:
            return candidates[0][0]

        # Multiple candidates with same score - use fallback for disambiguation
        if candidates[0][1] == candidates[1][1] and self._fallback:
            return await self._fallback.find_agent_for_intent(
                intent, registry, excluded_agents, rejection_context
            )

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
        excluded_agents: list[str] | None = None,
        rejection_context: str | None = None,
    ) -> "BaseAgent | None":
        """Try each router until one finds a match.

        :param intent: Natural language intent
        :param registry: Agent registry to search
        :param excluded_agents: Agent names to exclude from consideration
        :param rejection_context: Context about why previous routing failed
        :return: First matching agent found, or None
        """
        for router in self._routers:
            agent = await router.find_agent_for_intent(
                intent, registry, excluded_agents, rejection_context
            )
            if agent is not None:
                return agent
        return None


def get_default_router() -> IntentRouter:
    """Get the default intent router configuration.

    Returns an LLMIntentRouter for semantic intent understanding.
    We use LLM-only routing to enable agents to reason about
    the appropriate next step rather than relying on keyword matching.

    :return: Configured IntentRouter
    """
    return LLMIntentRouter()
