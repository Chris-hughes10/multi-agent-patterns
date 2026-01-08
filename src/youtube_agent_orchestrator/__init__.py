"""YouTube Agent - Multi-agent system for YouTube transcript search and summarization."""

from youtube_agent_orchestrator.models import Settings, StoredTranscript, get_settings
from youtube_agent_orchestrator.services import TranscriptStorage, fetch_transcript
from youtube_agent_orchestrator.tools import (
    load_transcript,
    save_transcript,
    summarize_transcript,
    summarize_video,
)

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "StoredTranscript",
    "TranscriptStorage",
    "fetch_transcript",
    "get_settings",
    "load_transcript",
    "save_transcript",
    "summarize_transcript",
    "summarize_video",
]
