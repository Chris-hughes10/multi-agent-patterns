"""Integration tests for transcript fetching that hit the real YouTube API."""

import pytest

from youtube_agent_orchestrator.tools.youtube import TranscriptFetchError, fetch_transcript


@pytest.mark.integration
class TestFetchTranscript:
    """Integration tests that hit the real YouTube API.

    These tests require network access and verify the full pipeline works.
    Use a stable, well-known video that's unlikely to be removed.
    """

    def test_fetches_real_transcript(self) -> None:
        """Should fetch a real transcript from YouTube."""
        # Rick Astley - Never Gonna Give You Up (stable, has captions)
        result = fetch_transcript("dQw4w9WgXcQ")

        assert result.metadata.video_id == "dQw4w9WgXcQ"
        assert len(result.transcript.segments) > 0
        assert result.transcript.duration_seconds > 0
        # The song has lyrics, so there should be substantial text
        assert len(result.transcript.full_text) > 100

    def test_fetch_with_url_format(self) -> None:
        """Should accept full YouTube URL and fetch transcript."""
        result = fetch_transcript("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert result.metadata.video_id == "dQw4w9WgXcQ"
        assert len(result.transcript.segments) > 0

    def test_raises_error_for_nonexistent_video(self) -> None:
        """Should raise TranscriptFetchError for invalid video."""
        with pytest.raises(TranscriptFetchError):
            fetch_transcript("xxxxxxxxxxx")  # 11 chars but doesn't exist
