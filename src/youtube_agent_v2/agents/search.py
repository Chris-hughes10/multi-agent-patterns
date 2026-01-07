"""SearchAgent - YouTube video search specialist."""

from collections.abc import Callable
from typing import Any

from youtube_agent.tools.search import search_youtube_formatted
from youtube_agent_v2.core.base_agent import BaseAgent

SEARCH_INSTRUCTIONS = """You are a YouTube Search Agent. Your job is to find relevant YouTube videos based on user queries.

When asked to search:
1. Use the search_youtube_formatted tool to find videos
2. Return the results clearly formatted
3. Highlight which videos seem most relevant to the query

You ONLY search - you do not fetch transcripts or summarize. Other agents handle those tasks.

Always return the video IDs so other agents can process the videos further."""


class SearchAgent(BaseAgent):
    """Agent specialized for YouTube video search.

    Capabilities: youtube_search, video_discovery

    Uses the search_youtube_formatted tool from V1 to find videos
    matching user queries.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "search"

    @property
    def capabilities(self) -> list[str]:
        """Return search-related capabilities."""
        return ["youtube_search", "video_discovery"]

    def _get_instructions(self) -> str:
        """Return search agent system prompt."""
        return SEARCH_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return search tools from V1."""
        return [search_youtube_formatted]
