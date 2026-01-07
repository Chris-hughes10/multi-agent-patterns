"""Services package - business logic classes organized by domain."""

from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.summarizer import SummarizationError, TranscriptSummarizer
from youtube_agent.services.youtube import (
    TranscriptFetcher,
    TranscriptFetchError,
    YouTubeSearchError,
    YouTubeTranscriptFetcher,
    extract_video_id,
    fetch_transcript,
    search_youtube,
)

__all__ = [
    # YouTube domain
    "TranscriptFetchError",
    "TranscriptFetcher",
    "YouTubeTranscriptFetcher",
    "YouTubeSearchError",
    "extract_video_id",
    "fetch_transcript",
    "search_youtube",
    # Storage domain
    "TranscriptStorage",
    # Summarization domain
    "TranscriptSummarizer",
    "SummarizationError",
]
