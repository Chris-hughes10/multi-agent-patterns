"""YouTube search tool using direct HTTP requests."""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field


@dataclass
class VideoSearchResult:
    """Result from a YouTube video search."""

    video_id: str
    title: str
    channel: str
    duration: str
    view_count: str | None
    published_time: str | None

    @property
    def url(self) -> str:
        """Get the full YouTube URL for this video."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


class YouTubeSearchError(Exception):
    """Raised when YouTube search fails."""

    def __init__(self, query: str, reason: str) -> None:
        self.query = query
        self.reason = reason
        super().__init__(f"YouTube search failed for '{query}': {reason}")


def _extract_videos_from_html(html: str, max_results: int) -> list[dict]:
    """Extract video data from YouTube search HTML response.

    :param html: Raw HTML from YouTube search page
    :param max_results: Maximum number of results to extract
    :return: List of video data dictionaries
    """
    # Find the initial data JSON embedded in the page
    match = re.search(r"var ytInitialData = ({.*?});</script>", html)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    videos = []

    # Navigate the nested structure to find video renderers
    try:
        contents = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                video_renderer = item.get("videoRenderer")
                if video_renderer and len(videos) < max_results:
                    video_id = video_renderer.get("videoId", "")
                    title_runs = video_renderer.get("title", {}).get("runs", [])
                    title = title_runs[0].get("text", "") if title_runs else ""

                    channel_runs = (
                        video_renderer.get("ownerText", {}).get("runs", [])
                    )
                    channel = channel_runs[0].get("text", "") if channel_runs else ""

                    duration_text = (
                        video_renderer.get("lengthText", {}).get("simpleText", "")
                    )

                    view_count_text = (
                        video_renderer.get("viewCountText", {}).get("simpleText")
                    )

                    published_text = (
                        video_renderer.get("publishedTimeText", {}).get("simpleText")
                    )

                    if video_id and title:
                        videos.append({
                            "video_id": video_id,
                            "title": title,
                            "channel": channel,
                            "duration": duration_text,
                            "view_count": view_count_text,
                            "published_time": published_text,
                        })
    except (KeyError, IndexError, TypeError):
        pass

    return videos


def search_youtube(
    query: Annotated[str, Field(description="Search query for YouTube videos")],
    max_results: Annotated[
        int, Field(description="Maximum number of results to return")
    ] = 5,
) -> list[VideoSearchResult]:
    """Search YouTube for videos matching the query.

    :param query: Search query string
    :param max_results: Maximum number of results (default 5)
    :return: List of VideoSearchResult objects
    :raises YouTubeSearchError: If the search fails
    """
    if not query or not query.strip():
        raise YouTubeSearchError(query, "Query cannot be empty")

    try:
        # Build search URL
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded_query}"

        # Make request with appropriate headers
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8")

        # Extract videos from HTML
        video_data = _extract_videos_from_html(html, max_results)

        return [
            VideoSearchResult(
                video_id=v["video_id"],
                title=v["title"],
                channel=v["channel"],
                duration=v["duration"],
                view_count=v["view_count"],
                published_time=v["published_time"],
            )
            for v in video_data
        ]

    except Exception as e:
        raise YouTubeSearchError(query, str(e)) from e


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
