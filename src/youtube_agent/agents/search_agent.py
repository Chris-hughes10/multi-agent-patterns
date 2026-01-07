"""Search Agent - finds YouTube videos by topic."""

from agent_framework import ChatAgent

from youtube_agent.infra.client import get_chat_client
from youtube_agent.tools.search import search_youtube_formatted

SEARCH_AGENT_INSTRUCTIONS = """You are a YouTube Search Agent. Your job is to find relevant YouTube videos based on user queries.

When asked to search:
1. Use the search_youtube tool to find videos
2. Return the results clearly formatted
3. Highlight which videos seem most relevant to the query

You only search - you do not fetch transcripts or summarize. Other agents handle those tasks."""


def create_search_agent() -> ChatAgent:
    """Create a Search Agent instance.

    :return: Configured ChatAgent for YouTube search
    """
    client = get_chat_client()

    return ChatAgent(
        chat_client=client,
        name="SearchAgent",
        instructions=SEARCH_AGENT_INSTRUCTIONS,
        tools=[search_youtube_formatted],
    )
