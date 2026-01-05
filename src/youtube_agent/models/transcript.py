"""Data models for YouTube transcripts."""

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single segment of a transcript with timing information.

    :param text: The text content of this segment
    :param start: Start time in seconds
    :param duration: Duration of this segment in seconds
    """

    text: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        """Calculate the end time of this segment."""
        return self.start + self.duration


class Transcript(BaseModel):
    """A complete transcript for a YouTube video.

    :param video_id: The YouTube video ID
    :param segments: List of transcript segments with timing
    :param language: Language code of the transcript (e.g., 'en')
    :param is_generated: Whether this is an auto-generated transcript
    """

    video_id: str
    segments: list[TranscriptSegment]
    language: str = "en"
    is_generated: bool = False

    @property
    def full_text(self) -> str:
        """Get the complete transcript as a single string."""
        return " ".join(segment.text for segment in self.segments)

    @property
    def duration_seconds(self) -> float:
        """Get the total duration covered by the transcript."""
        if not self.segments:
            return 0.0
        last_segment = self.segments[-1]
        return last_segment.end

    def get_text_at_time(self, time_seconds: float) -> str | None:
        """Find the transcript text at a specific time.

        :param time_seconds: The time in seconds to look up
        :return: The text at that time, or None if not found
        """
        for segment in self.segments:
            if segment.start <= time_seconds < segment.end:
                return segment.text
        return None


class VideoMetadata(BaseModel):
    """Basic metadata about a YouTube video.

    :param video_id: The YouTube video ID
    :param title: Video title (if available)
    :param channel: Channel name (if available)
    :param url: Full YouTube URL
    """

    video_id: str
    title: str | None = None
    channel: str | None = None

    @property
    def url(self) -> str:
        """Get the full YouTube URL for this video."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


class TranscriptResult(BaseModel):
    """Result of fetching a transcript, including metadata.

    :param metadata: Video metadata
    :param transcript: The transcript content
    """

    metadata: VideoMetadata
    transcript: Transcript

    @property
    def summary_context(self) -> str:
        """Get formatted context suitable for LLM summarization."""
        parts = [f"Video: {self.metadata.title or self.metadata.video_id}"]
        if self.metadata.channel:
            parts.append(f"Channel: {self.metadata.channel}")
        parts.append(f"URL: {self.metadata.url}")
        parts.append("")
        parts.append("Transcript:")
        parts.append(self.transcript.full_text)
        return "\n".join(parts)
