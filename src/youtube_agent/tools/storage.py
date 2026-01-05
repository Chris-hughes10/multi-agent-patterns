"""JSON-based storage for YouTube transcripts and summaries."""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from youtube_agent.models.config import get_settings
from youtube_agent.models.transcript import Transcript, TranscriptResult, VideoMetadata


class StoredTranscript(BaseModel):
    """A transcript stored on disk with additional metadata.

    :param video_id: The YouTube video ID
    :param transcript: The transcript content
    :param metadata: Video metadata
    :param summary: Optional summary of the transcript
    :param stored_at: When the transcript was stored
    :param updated_at: When the transcript was last updated
    """

    video_id: str
    transcript: Transcript
    metadata: VideoMetadata
    summary: str | None = None
    stored_at: datetime
    updated_at: datetime


class TranscriptStorage:
    """Manages storage and retrieval of transcripts as JSON files.

    Transcripts are stored as individual JSON files keyed by video ID.
    Each file contains the transcript, metadata, and optional summary.

    :param storage_dir: Directory to store transcripts (defaults to settings)
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        settings = get_settings()
        self._storage_dir = storage_dir or settings.storage_dir
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Create storage directory if it doesn't exist."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, video_id: str) -> Path:
        """Get the file path for a video's transcript."""
        return self._storage_dir / f"{video_id}.json"

    def save(
        self,
        result: TranscriptResult,
        summary: str | None = None,
    ) -> StoredTranscript:
        """Save a transcript result to storage.

        If the transcript already exists, it will be updated.

        :param result: The transcript result to save
        :param summary: Optional summary to store alongside
        :return: The stored transcript with metadata
        """
        video_id = result.metadata.video_id
        path = self._get_path(video_id)
        now = datetime.now(UTC)

        # Check if updating existing
        existing = self.load(video_id)
        stored_at = existing.stored_at if existing else now

        stored = StoredTranscript(
            video_id=video_id,
            transcript=result.transcript,
            metadata=result.metadata,
            summary=summary or (existing.summary if existing else None),
            stored_at=stored_at,
            updated_at=now,
        )

        path.write_text(stored.model_dump_json(indent=2))
        return stored

    def load(self, video_id: str) -> StoredTranscript | None:
        """Load a transcript from storage.

        :param video_id: The video ID to load
        :return: The stored transcript, or None if not found
        """
        path = self._get_path(video_id)
        if not path.exists():
            return None

        data = json.loads(path.read_text())
        return StoredTranscript.model_validate(data)

    def exists(self, video_id: str) -> bool:
        """Check if a transcript exists in storage.

        :param video_id: The video ID to check
        :return: True if the transcript exists
        """
        return self._get_path(video_id).exists()

    def delete(self, video_id: str) -> bool:
        """Delete a transcript from storage.

        :param video_id: The video ID to delete
        :return: True if the transcript was deleted, False if it didn't exist
        """
        path = self._get_path(video_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_videos(self) -> list[str]:
        """List all stored video IDs.

        :return: List of video IDs with stored transcripts
        """
        return [path.stem for path in self._storage_dir.glob("*.json")]

    def update_summary(self, video_id: str, summary: str) -> StoredTranscript | None:
        """Update just the summary for an existing transcript.

        :param video_id: The video ID to update
        :param summary: The new summary
        :return: The updated stored transcript, or None if not found
        """
        stored = self.load(video_id)
        if stored is None:
            return None

        stored.summary = summary
        stored.updated_at = datetime.now(UTC)

        path = self._get_path(video_id)
        path.write_text(stored.model_dump_json(indent=2))
        return stored


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
