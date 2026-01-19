"""Storage tools - convenience functions for transcript storage.

This module contains convenience functions for storage operations.
Business logic is in services/storage.py, model is in models/storage.py.
"""

from youtube_agent_orchestrator.models.storage import StoredTranscript
from youtube_agent_orchestrator.models.youtube import TranscriptResult
from youtube_agent_orchestrator.services.storage import TranscriptStorage

__all__ = [
    "StoredTranscript",
    "TranscriptStorage",
    "save_transcript",
    "load_transcript",
]


def save_transcript(
    result: TranscriptResult,
    summary: str | None = None,
    storage: TranscriptStorage | None = None,
) -> StoredTranscript:
    """Save a transcript to storage - convenience function.

    :param result: The transcript result to save
    :param summary: Optional summary to store
    :param storage: Optional custom storage instance
    :return: The stored transcript
    """
    storage = storage or TranscriptStorage()
    return storage.save(result, summary)


def load_transcript(
    video_id: str,
    storage: TranscriptStorage | None = None,
) -> StoredTranscript | None:
    """Load a transcript from storage - convenience function.

    :param video_id: The video ID to load
    :param storage: Optional custom storage instance
    :return: The stored transcript, or None if not found
    """
    storage = storage or TranscriptStorage()
    return storage.load(video_id)
