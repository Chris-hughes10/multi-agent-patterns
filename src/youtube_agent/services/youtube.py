"""YouTube domain services - transcript fetching and search.

This module contains all YouTube-related business logic, organized by domain
(DDD-aligned) rather than by functionality. Both search and transcript fetching
belong to the YouTube bounded context as they share domain concepts like
video_id, channel, and transcript.

Search functions are async to avoid blocking the event loop.
Transcript fetching uses asyncio.to_thread() to wrap the sync third-party library.
"""

import asyncio
import json
import re
import urllib.parse
from typing import Protocol

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from youtube_agent.models.config import get_settings
from youtube_agent.models.search import VideoSearchResult
from youtube_agent.models.transcript import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
)

# =============================================================================
# Exceptions
# =============================================================================


class TranscriptFetchError(Exception):
    """Raised when a transcript cannot be fetched.

    :param video_id: The video ID that failed
    :param reason: Human-readable reason for the failure
    """

    def __init__(self, video_id: str, reason: str) -> None:
        self.video_id = video_id
        self.reason = reason
        super().__init__(f"Failed to fetch transcript for {video_id}: {reason}")


class YouTubeSearchError(Exception):
    """Raised when YouTube search fails."""

    def __init__(self, query: str, reason: str) -> None:
        self.query = query
        self.reason = reason
        super().__init__(f"YouTube search failed for '{query}': {reason}")


# =============================================================================
# Transcript Fetching
# =============================================================================


class TranscriptFetcher(Protocol):
    """Protocol for transcript fetching implementations.

    Allows for dependency injection and testing.
    """

    def fetch(self, video_id: str, languages: list[str] | None = None) -> Transcript:
        """Fetch transcript for a video.

        :param video_id: YouTube video ID
        :param languages: Preferred languages in order of preference
        :return: The fetched transcript
        :raises TranscriptFetchError: If transcript cannot be fetched
        """
        ...


class YouTubeTranscriptFetcher:
    """Fetches transcripts from YouTube using youtube-transcript-api.

    :param proxy_url: Optional proxy URL (e.g., http://user:pass@host:port)
    """

    def __init__(self, proxy_url: str | None = None) -> None:
        self._proxy_url = proxy_url

    def _create_api(self) -> YouTubeTranscriptApi:
        """Create YouTubeTranscriptApi instance with optional proxy."""
        if self._proxy_url:
            proxy_config = GenericProxyConfig(https_url=self._proxy_url)
            return YouTubeTranscriptApi(proxy_config=proxy_config)
        return YouTubeTranscriptApi()

    def fetch(
        self,
        video_id: str,
        languages: list[str] | None = None,
    ) -> Transcript:
        """Fetch transcript for a YouTube video.

        :param video_id: YouTube video ID (e.g., 'dQw4w9WgXcQ')
        :param languages: Preferred languages, defaults to ['en']
        :return: Transcript object with segments and metadata
        :raises TranscriptFetchError: If transcript is unavailable or disabled
        """
        languages = languages or ["en"]

        try:
            api = self._create_api()
            fetched = api.fetch(video_id, languages=languages)
            segments = [
                TranscriptSegment(
                    text=snippet.text,
                    start=snippet.start,
                    duration=snippet.duration,
                )
                for snippet in fetched
            ]

            return Transcript(
                video_id=video_id,
                segments=segments,
                language=languages[0],
                is_generated=False,
            )

        except TranscriptsDisabled:
            error_msg = "Transcripts are disabled for this video"
            if not self._proxy_url:
                error_msg += (
                    " (Note: If running in a cloud/data center environment, "
                    "YouTube may be blocking your IP. Try setting PROXY_URL in .env)"
                )
            raise TranscriptFetchError(video_id, error_msg) from None
        except NoTranscriptFound:
            raise TranscriptFetchError(
                video_id, f"No transcript found for languages: {languages}"
            ) from None
        except VideoUnavailable:
            raise TranscriptFetchError(video_id, "Video is unavailable") from None
        except Exception as e:
            error_msg = str(e)
            # Detect potential proxy-related issues
            if not self._proxy_url and any(
                keyword in error_msg.lower()
                for keyword in ["timeout", "connection", "blocked", "forbidden", "403"]
            ):
                error_msg += (
                    " (Possible network/IP block. If running in a cloud environment, "
                    "set PROXY_URL in .env to use a residential proxy)"
                )
            raise TranscriptFetchError(video_id, error_msg) from e


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from a YouTube URL or return the ID if already provided.

    Supports various YouTube URL formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - VIDEO_ID (11 character ID)

    :param url_or_id: YouTube URL or video ID
    :return: The extracted video ID
    :raises ValueError: If the URL/ID format is not recognized
    """
    # Already a video ID (11 alphanumeric characters, hyphens, underscores)
    if re.match(r"^[\w-]{11}$", url_or_id):
        return url_or_id

    # Try to extract from URL
    patterns = [
        r"(?:youtube\.com/watch\?v=)([\w-]{11})",
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:youtube\.com/embed/)([\w-]{11})",
        r"(?:youtube\.com/v/)([\w-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def _fetch_transcript_sync(
    url_or_id: str,
    languages: list[str] | None = None,
    fetcher: TranscriptFetcher | None = None,
) -> TranscriptResult:
    """Synchronous implementation of transcript fetching.

    This is the internal sync version. Use fetch_transcript() for the async API.
    """
    video_id = extract_video_id(url_or_id)

    if fetcher is None:
        settings = get_settings()
        fetcher = YouTubeTranscriptFetcher(proxy_url=settings.proxy_url)

    transcript = fetcher.fetch(video_id, languages)

    metadata = VideoMetadata(video_id=video_id)

    return TranscriptResult(metadata=metadata, transcript=transcript)


async def fetch_transcript(
    url_or_id: str,
    languages: list[str] | None = None,
    fetcher: TranscriptFetcher | None = None,
) -> TranscriptResult:
    """Fetch a transcript from YouTube - main entry point.

    This is the primary function to use for fetching transcripts.
    It handles URL parsing and returns a complete result with metadata.

    Uses asyncio.to_thread() to run the sync youtube-transcript-api
    in a thread pool, avoiding blocking the event loop.

    Uses proxy from settings if configured (PROXY_URL environment variable).

    :param url_or_id: YouTube URL or video ID
    :param languages: Preferred languages, defaults to ['en']
    :param fetcher: Optional custom fetcher for dependency injection
    :return: TranscriptResult with transcript and metadata
    :raises TranscriptFetchError: If transcript cannot be fetched
    :raises ValueError: If video ID cannot be extracted from URL

    Example::

        result = await fetch_transcript("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print(result.transcript.full_text)
    """
    return await asyncio.to_thread(_fetch_transcript_sync, url_or_id, languages, fetcher)


# =============================================================================
# YouTube Search
# =============================================================================


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

                    channel_runs = video_renderer.get("ownerText", {}).get("runs", [])
                    channel = channel_runs[0].get("text", "") if channel_runs else ""

                    duration_text = video_renderer.get("lengthText", {}).get("simpleText", "")

                    view_count_text = video_renderer.get("viewCountText", {}).get("simpleText")

                    published_text = video_renderer.get("publishedTimeText", {}).get("simpleText")

                    if video_id and title:
                        videos.append(
                            {
                                "video_id": video_id,
                                "title": title,
                                "channel": channel,
                                "duration": duration_text,
                                "view_count": view_count_text,
                                "published_time": published_text,
                            }
                        )
    except (KeyError, IndexError, TypeError):
        pass

    return videos


async def search_youtube(query: str, max_results: int = 5) -> list[VideoSearchResult]:
    """Search YouTube for videos matching the query.

    This is an async function that uses httpx for non-blocking HTTP requests.

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

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            html = response.text

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

    except YouTubeSearchError:
        raise
    except Exception as e:
        raise YouTubeSearchError(query, str(e)) from e
