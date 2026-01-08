"""YouTube search tool - LLM-callable wrapper.

This module contains only the tool function that exposes the search
service to the LLM. Business logic is in services/youtube.py.

All tool functions are async to avoid blocking the event loop.
"""

import json
from typing import Annotated

from pydantic import Field

# Re-export for backwards compatibility
from youtube_agent_orchestrator.models.search import VideoSearchResult
from youtube_agent_orchestrator.services.youtube import YouTubeSearchError, search_youtube

__all__ = [
    "VideoSearchResult",
    "YouTubeSearchError",
    "search_youtube_formatted",
    "search_youtube_structured",
]


async def search_youtube_formatted(
    query: Annotated[str, Field(description="Search query for YouTube videos")],
    max_results: Annotated[int, Field(description="Maximum number of results to return")] = 5,
) -> str:
    """Search YouTube and return formatted string results.

    This is the agent-friendly async version that returns a formatted string
    suitable for LLM consumption.

    :param query: Search query string
    :param max_results: Maximum number of results (default 5)
    :return: Formatted string with search results
    """
    results = await search_youtube(query, max_results)

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


async def search_youtube_structured(
    query: Annotated[str, Field(description="Search query for YouTube videos")],
    max_results: Annotated[int, Field(description="Maximum number of results to return")] = 5,
) -> str:
    """Search YouTube and return structured JSON results.

    Returns a JSON string with structured data that can be used for
    DAG variable resolution (e.g., $search.results[0].video_id).

    :param query: Search query string
    :param max_results: Maximum number of results (default 5)
    :return: JSON string with query and results array
    """
    results = await search_youtube(query, max_results)

    output = {
        "query": query,
        "count": len(results),
        "results": [
            {
                "video_id": video.video_id,
                "title": video.title,
                "channel": video.channel,
                "duration": video.duration,
                "view_count": video.view_count,
                "published_time": video.published_time,
            }
            for video in results
        ],
    }

    return json.dumps(output, indent=2)
