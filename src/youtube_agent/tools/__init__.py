"""Tools that agents can use - YouTube search, transcript fetch, etc."""

from youtube_agent.tools.search import (
    VideoSearchResult,
    YouTubeSearchError,
    search_youtube,
    search_youtube_formatted,
)
from youtube_agent.tools.storage import (
    StoredTranscript,
    TranscriptStorage,
    load_transcript,
    save_transcript,
)
from youtube_agent.tools.summarize import (
    SummarizationError,
    TranscriptSummarizer,
    summarize_transcript,
    summarize_video,
)
from youtube_agent.tools.transcript import (
    TranscriptFetcher,
    TranscriptFetchError,
    YouTubeTranscriptFetcher,
    extract_video_id,
    fetch_transcript,
)

__all__ = [
    # YouTube search
    "VideoSearchResult",
    "YouTubeSearchError",
    "search_youtube",
    "search_youtube_formatted",
    # Transcript fetching
    "TranscriptFetchError",
    "TranscriptFetcher",
    "YouTubeTranscriptFetcher",
    "extract_video_id",
    "fetch_transcript",
    # Storage
    "StoredTranscript",
    "TranscriptStorage",
    "load_transcript",
    "save_transcript",
    # Summarization
    "SummarizationError",
    "TranscriptSummarizer",
    "summarize_transcript",
    "summarize_video",
]
