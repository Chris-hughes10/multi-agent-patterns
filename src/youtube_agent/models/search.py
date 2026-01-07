"""Search-related data models."""

from dataclasses import dataclass


@dataclass
class VideoSearchResult:
    """Result from a YouTube video search."""

    video_id: str
    title: str
    channel: str
    duration: str
    view_count: str | None
    published_time: str | None

    @property
    def url(self) -> str:
        """Get the full YouTube URL for this video."""
        return f"https://www.youtube.com/watch?v={self.video_id}"
