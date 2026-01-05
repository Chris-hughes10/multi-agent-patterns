"""YouTube Agent - Multi-agent system for YouTube transcript search and summarization."""

from youtube_agent.models import Settings, get_settings
from youtube_agent.tools import fetch_transcript

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "fetch_transcript",
    "get_settings",
]
