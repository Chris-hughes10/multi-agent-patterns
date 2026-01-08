"""Storage-related data models."""

from datetime import datetime

from pydantic import BaseModel

from youtube_agent_orchestrator.models.transcript import Transcript, VideoMetadata


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
