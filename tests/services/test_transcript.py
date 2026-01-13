"""Tests for transcript fetching tool."""

import pytest

from youtube_agent_orchestrator.models.youtube import Transcript, TranscriptSegment
from youtube_agent_orchestrator.tools.youtube import extract_video_id


class TestExtractVideoId:
    """Tests for video ID extraction from URLs."""

    @pytest.mark.parametrize(
        "input_value,expected_id",
        [
            # Direct video ID
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # Standard watch URL
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # Short URL
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # Embed URL
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # With additional parameters
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120", "dQw4w9WgXcQ"),
            # Without www
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # With hyphens and underscores in ID
            ("abc-def_123", "abc-def_123"),
        ],
    )
    def test_extracts_video_id_from_various_formats(
        self, input_value: str, expected_id: str
    ) -> None:
        """Should extract video ID from various URL formats and direct IDs."""
        assert extract_video_id(input_value) == expected_id

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "not-a-valid-url",
            "https://example.com/video",
            "tooshort",
            "waytoolongtobeavalidvideoid",
            "",
        ],
    )
    def test_raises_value_error_for_invalid_input(self, invalid_input: str) -> None:
        """Should raise ValueError for inputs that don't contain a valid video ID."""
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id(invalid_input)


class TestTranscript:
    """Tests for Transcript model behavior."""

    def test_full_text_concatenates_segments(self) -> None:
        """Should join all segment texts with spaces."""
        transcript = Transcript(
            video_id="test1234567",
            segments=[
                TranscriptSegment(text="Hello", start=0.0, duration=2.0),
                TranscriptSegment(text="world", start=2.0, duration=2.0),
            ],
        )
        assert transcript.full_text == "Hello world"

    def test_duration_seconds_returns_zero_for_empty_transcript(self) -> None:
        """Should return 0 for transcript with no segments."""
        transcript = Transcript(video_id="test1234567", segments=[])
        assert transcript.duration_seconds == 0.0

    def test_get_text_at_time_returns_correct_segment(self) -> None:
        """Should return text for segment containing the given time."""
        transcript = Transcript(
            video_id="test1234567",
            segments=[
                TranscriptSegment(text="first", start=0.0, duration=2.0),
                TranscriptSegment(text="second", start=2.0, duration=2.0),
                TranscriptSegment(text="third", start=4.0, duration=2.0),
            ],
        )
        assert transcript.get_text_at_time(1.0) == "first"
        assert transcript.get_text_at_time(3.0) == "second"
        assert transcript.get_text_at_time(5.0) == "third"

    def test_get_text_at_time_returns_none_outside_range(self) -> None:
        """Should return None for times not covered by any segment."""
        transcript = Transcript(
            video_id="test1234567",
            segments=[TranscriptSegment(text="only", start=0.0, duration=2.0)],
        )
        assert transcript.get_text_at_time(10.0) is None
        assert transcript.get_text_at_time(-1.0) is None
