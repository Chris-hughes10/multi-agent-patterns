"""Driver module - shared logic for CLI and programmatic usage.

This module provides the core driver functions that can be used by:
- CLI commands
- E2E tests
- Programmatic API consumers
"""

import logging
from datetime import datetime
from pathlib import Path

from youtube_agent_orchestrator.agents.orchestrator import (
    OrchestratorAgent,
    create_orchestrator,
)
from youtube_agent_orchestrator.models.storage import StoredTranscript
from youtube_agent_orchestrator.models.youtube import TranscriptResult
from youtube_agent_orchestrator.services.storage import TranscriptStorage
from youtube_agent_orchestrator.services.youtube import fetch_transcript
from youtube_agent_orchestrator.tools.youtube import search_youtube_formatted
from youtube_agent_orchestrator.tools.summarize import summarize_video

logger = logging.getLogger("youtube_agent_orchestrator.driver")


def setup_logging(debug: bool = False) -> str | None:
    """Configure logging for the application.

    :param debug: If True, enable DEBUG level logging
    :return: Path to log file if debug mode, None otherwise
    """
    level = logging.DEBUG if debug else logging.WARNING
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"

    # Basic console logging
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
    )

    log_file_path = None

    # Also log to file in debug mode
    if debug:
        log_dir = Path("data/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = log_dir / f"session_{timestamp}.log"

        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

        # Add file handler to root logger
        logging.getLogger().addHandler(file_handler)

        # Enable debug for httpx/openai to see API calls
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

        logger.info("Logging to file: %s", log_file_path)

    return str(log_file_path) if log_file_path else None


async def process_request(
    request: str,
    orchestrator: OrchestratorAgent | None = None,
) -> str:
    """Process a user request through the orchestrator agent system.

    This is the main driver function that handles:
    - Creating the orchestrator (if not provided)
    - Processing the request
    - Returning the response

    :param request: Natural language user request
    :param orchestrator: Optional pre-created orchestrator (creates new if None)
    :return: Response string from the orchestrator
    """
    if orchestrator is None:
        orchestrator = create_orchestrator()

    return await orchestrator.run(request)


async def search_videos(query: str, max_results: int = 5) -> str:
    """Search YouTube for videos matching the query.

    :param query: Search query string
    :param max_results: Maximum number of results to return
    :return: Formatted search results string
    """
    return await search_youtube_formatted(query, max_results)


def get_transcript(video: str, save: bool = False) -> TranscriptResult:
    """Fetch transcript for a YouTube video.

    :param video: YouTube video URL or ID
    :param save: Whether to save the transcript to storage
    :return: TranscriptResult with metadata and transcript
    """
    result = fetch_transcript(video)

    if save:
        storage = TranscriptStorage()
        storage.save(result)

    return result


def get_summary(video: str, save: bool = True) -> StoredTranscript:
    """Fetch transcript and generate summary for a YouTube video.

    :param video: YouTube video URL or ID
    :param save: Whether to save to storage
    :return: StoredTranscript with summary
    """
    return summarize_video(video, save=save)


def list_stored_transcripts() -> list[dict]:
    """List all stored transcripts.

    :return: List of dicts with video_id, title, and has_summary
    """
    storage = TranscriptStorage()
    video_ids = storage.list_videos()

    results = []
    for vid in video_ids:
        stored = storage.load(vid)
        if stored:
            results.append({
                "video_id": vid,
                "title": stored.metadata.title or "Unknown",
                "has_summary": bool(stored.summary),
            })

    return results


def lookup_transcript(video_id: str) -> StoredTranscript | None:
    """Look up a stored transcript by video ID.

    :param video_id: YouTube video ID
    :return: StoredTranscript if found, None otherwise
    """
    storage = TranscriptStorage()
    return storage.load(video_id)


# Re-export create_orchestrator for convenience
__all__ = [
    "setup_logging",
    "process_request",
    "search_videos",
    "get_transcript",
    "get_summary",
    "list_stored_transcripts",
    "lookup_transcript",
    "create_orchestrator",
]
