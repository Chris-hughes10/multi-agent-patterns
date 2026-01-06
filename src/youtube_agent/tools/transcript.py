"""Tool for fetching YouTube video transcripts."""

import re
from typing import Protocol

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from youtube_agent.models.config import get_settings
from youtube_agent.models.transcript import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
)


class TranscriptFetchError(Exception):
    """Raised when a transcript cannot be fetched.

    :param video_id: The video ID that failed
    :param reason: Human-readable reason for the failure
    """

    def __init__(self, video_id: str, reason: str) -> None:
        self.video_id = video_id
        self.reason = reason
        super().__init__(f"Failed to fetch transcript for {video_id}: {reason}")


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
            raise TranscriptFetchError(
                video_id, "Transcripts are disabled for this video"
            ) from None
        except NoTranscriptFound:
            raise TranscriptFetchError(
                video_id, f"No transcript found for languages: {languages}"
            ) from None
        except VideoUnavailable:
            raise TranscriptFetchError(video_id, "Video is unavailable") from None
        except Exception as e:
            raise TranscriptFetchError(video_id, str(e)) from e


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


def fetch_transcript(
    url_or_id: str,
    languages: list[str] | None = None,
    fetcher: TranscriptFetcher | None = None,
) -> TranscriptResult:
    """Fetch a transcript from YouTube - main entry point.

    This is the primary function to use for fetching transcripts.
    It handles URL parsing and returns a complete result with metadata.

    Uses proxy from settings if configured (PROXY_URL environment variable).

    :param url_or_id: YouTube URL or video ID
    :param languages: Preferred languages, defaults to ['en']
    :param fetcher: Optional custom fetcher for dependency injection
    :return: TranscriptResult with transcript and metadata
    :raises TranscriptFetchError: If transcript cannot be fetched
    :raises ValueError: If video ID cannot be extracted from URL

    Example::

        result = fetch_transcript("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print(result.transcript.full_text)
    """
    video_id = extract_video_id(url_or_id)

    if fetcher is None:
        settings = get_settings()
        fetcher = YouTubeTranscriptFetcher(proxy_url=settings.proxy_url)

    transcript = fetcher.fetch(video_id, languages)

    metadata = VideoMetadata(video_id=video_id)

    return TranscriptResult(metadata=metadata, transcript=transcript)
