"""YouTube search tool - LLM-callable wrapper.

This module contains only the tool function that exposes the search
service to the LLM. Business logic is in services/youtube.py.
"""

from typing import Annotated

from pydantic import Field

# Re-export for backwards compatibility
from youtube_agent.models.search import VideoSearchResult
from youtube_agent.services.youtube import YouTubeSearchError, search_youtube

__all__ = ["VideoSearchResult", "YouTubeSearchError", "search_youtube_formatted"]


def search_youtube_formatted(
    query: Annotated[str, Field(description="Search query for YouTube videos")],
    max_results: Annotated[
        int, Field(description="Maximum number of results to return")
    ] = 5,
) -> str:
    """Search YouTube and return formatted string results.

    This is the agent-friendly version that returns a formatted string
    suitable for LLM consumption.

    :param query: Search query string
    :param max_results: Maximum number of results (default 5)
    :return: Formatted string with search results
    """
    results = search_youtube(query, max_results)

    if not results:
        return f"No videos found for query: {query}"

    lines = [f"Found {len(results)} videos for '{query}':\n"]
    for i, video in enumerate(results, 1):
        lines.append(f"{i}. {video.title}")
        lines.append(f"   Channel: {video.channel}")
        lines.append(f"   Duration: {video.duration}")
        lines.append(f"   Video ID: {video.video_id}")
        if video.view_count:
            lines.append(f"   Views: {video.view_count}")
        lines.append("")

    return "\n".join(lines)
