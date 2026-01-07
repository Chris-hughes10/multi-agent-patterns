"""Tools package - LLM-callable tool functions.

This package contains thin wrappers that expose services to agents.
Business logic is in the services/ package.
"""

from youtube_agent.tools.search import search_youtube_formatted
from youtube_agent.tools.storage import load_transcript, save_transcript
from youtube_agent.tools.summarize import (
    summarize_stored_transcript,
    summarize_text,
    summarize_transcript,
    summarize_video,
)
from youtube_agent.tools.transcript import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
    store_video_transcript,
)

__all__ = [
    "search_youtube_formatted",
    "fetch_video_transcript",
    "store_video_transcript",
    "lookup_stored_transcript",
    "list_stored_transcripts",
    "summarize_stored_transcript",
    "summarize_text",
    "summarize_transcript",
    "summarize_video",
    "load_transcript",
    "save_transcript",
]
