"""CLI layer for the YouTube Agent.

- commands.py: Click-based CLI commands
- main.py: Driver functions for programmatic usage
- status.py: Human-friendly status monitoring
"""

from youtube_agent_orchestrator.cli.commands import main
from youtube_agent_orchestrator.cli.main import (
    create_orchestrator,
    get_summary,
    get_transcript,
    list_stored_transcripts,
    lookup_transcript,
    process_request,
    search_videos,
    setup_logging,
)

__all__ = [
    # CLI entry point
    "main",
    # Driver functions
    "setup_logging",
    "process_request",
    "search_videos",
    "get_transcript",
    "get_summary",
    "list_stored_transcripts",
    "lookup_transcript",
    "create_orchestrator",
]
