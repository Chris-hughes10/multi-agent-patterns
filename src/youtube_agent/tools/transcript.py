"""Tool for fetching YouTube video transcripts."""

import re
from typing import Protocol

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

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

    :param api: Optional YouTubeTranscriptApi instance for dependency injection
    """

    def __init__(self, api: YouTubeTranscriptApi | None = None) -> None:
        self._api = api or YouTubeTranscriptApi()

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
            transcript_data = self._api.fetch(video_id)
            segments = [
                TranscriptSegment(
                    text=entry.text,
                    start=entry.start,
                    duration=entry.duration,
                )
                for entry in transcript_data
            ]

            return Transcript(
                video_id=video_id,
                segments=segments,
                language=languages[0],
                is_generated=False,
            )

        except TranscriptsDisabled:
            raise TranscriptFetchError(video_id, "Transcripts are disabled for this video")
        except NoTranscriptFound:
            raise TranscriptFetchError(
                video_id, f"No transcript found for languages: {languages}"
            )
        except VideoUnavailable:
            raise TranscriptFetchError(video_id, "Video is unavailable")
        except Exception as e:
            raise TranscriptFetchError(video_id, str(e))


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
    fetcher = fetcher or YouTubeTranscriptFetcher()

    transcript = fetcher.fetch(video_id, languages)

    metadata = VideoMetadata(video_id=video_id)

    return TranscriptResult(metadata=metadata, transcript=transcript)
