"""Tests for transcript fetching tool."""

import pytest

from youtube_agent.models.transcript import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
)
from youtube_agent.tools.transcript import (
    TranscriptFetchError,
    TranscriptFetcher,
    extract_video_id,
    fetch_transcript,
)


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
        result = extract_video_id(input_value)
        assert result == expected_id

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


class TestTranscriptSegment:
    """Tests for TranscriptSegment model."""

    def test_calculates_end_time(self) -> None:
        """Should calculate end time from start and duration."""
        segment = TranscriptSegment(text="Hello", start=10.0, duration=5.0)
        assert segment.end == 15.0

    def test_stores_text_content(self) -> None:
        """Should store and retrieve text content."""
        segment = TranscriptSegment(text="Test content", start=0.0, duration=1.0)
        assert segment.text == "Test content"


class TestTranscript:
    """Tests for Transcript model."""

    @pytest.fixture
    def sample_transcript(self) -> Transcript:
        """Create a sample transcript for testing."""
        return Transcript(
            video_id="test123",
            segments=[
                TranscriptSegment(text="Hello", start=0.0, duration=2.0),
                TranscriptSegment(text="world", start=2.0, duration=2.0),
                TranscriptSegment(text="test", start=4.0, duration=2.0),
            ],
            language="en",
        )

    def test_full_text_concatenates_segments(self, sample_transcript: Transcript) -> None:
        """Should join all segment texts with spaces."""
        assert sample_transcript.full_text == "Hello world test"

    def test_duration_seconds_returns_end_of_last_segment(
        self, sample_transcript: Transcript
    ) -> None:
        """Should return the end time of the last segment."""
        assert sample_transcript.duration_seconds == 6.0

    def test_duration_seconds_returns_zero_for_empty_transcript(self) -> None:
        """Should return 0 for transcript with no segments."""
        transcript = Transcript(video_id="empty", segments=[])
        assert transcript.duration_seconds == 0.0

    def test_get_text_at_time_returns_correct_segment(
        self, sample_transcript: Transcript
    ) -> None:
        """Should return text for segment containing the given time."""
        assert sample_transcript.get_text_at_time(1.0) == "Hello"
        assert sample_transcript.get_text_at_time(3.0) == "world"
        assert sample_transcript.get_text_at_time(5.0) == "test"

    def test_get_text_at_time_returns_none_for_time_outside_range(
        self, sample_transcript: Transcript
    ) -> None:
        """Should return None for times not covered by any segment."""
        assert sample_transcript.get_text_at_time(10.0) is None
        assert sample_transcript.get_text_at_time(-1.0) is None


class TestVideoMetadata:
    """Tests for VideoMetadata model."""

    def test_url_property_builds_youtube_url(self) -> None:
        """Should construct full YouTube URL from video ID."""
        metadata = VideoMetadata(video_id="abc123def45")
        assert metadata.url == "https://www.youtube.com/watch?v=abc123def45"

    def test_optional_fields_default_to_none(self) -> None:
        """Should allow title and channel to be None."""
        metadata = VideoMetadata(video_id="test")
        assert metadata.title is None
        assert metadata.channel is None


class TestTranscriptResult:
    """Tests for TranscriptResult model."""

    def test_summary_context_formats_for_llm(self) -> None:
        """Should format transcript with metadata for LLM consumption."""
        result = TranscriptResult(
            metadata=VideoMetadata(
                video_id="test123",
                title="Test Video",
                channel="Test Channel",
            ),
            transcript=Transcript(
                video_id="test123",
                segments=[TranscriptSegment(text="Content here", start=0.0, duration=1.0)],
            ),
        )

        context = result.summary_context
        assert "Video: Test Video" in context
        assert "Channel: Test Channel" in context
        assert "https://www.youtube.com/watch?v=test123" in context
        assert "Content here" in context


class FakeTranscriptFetcher:
    """Fake fetcher for testing without hitting YouTube API."""

    def __init__(self, transcript: Transcript | None = None, error: Exception | None = None):
        self._transcript = transcript
        self._error = error
        self.fetch_calls: list[tuple[str, list[str] | None]] = []

    def fetch(self, video_id: str, languages: list[str] | None = None) -> Transcript:
        """Record the call and return configured response."""
        self.fetch_calls.append((video_id, languages))
        if self._error:
            raise self._error
        if self._transcript:
            return self._transcript
        return Transcript(video_id=video_id, segments=[])


class TestFetchTranscript:
    """Tests for the main fetch_transcript function."""

    def test_extracts_id_and_delegates_to_fetcher(self) -> None:
        """Should extract video ID from URL and use provided fetcher."""
        fake_fetcher = FakeTranscriptFetcher()

        fetch_transcript(
            "https://www.youtube.com/watch?v=abc12345678",
            fetcher=fake_fetcher,
        )

        assert len(fake_fetcher.fetch_calls) == 1
        assert fake_fetcher.fetch_calls[0][0] == "abc12345678"

    def test_returns_transcript_result_with_metadata(self) -> None:
        """Should return TranscriptResult with video metadata."""
        transcript = Transcript(
            video_id="test123video",
            segments=[TranscriptSegment(text="Hello", start=0.0, duration=1.0)],
        )
        fake_fetcher = FakeTranscriptFetcher(transcript=transcript)

        result = fetch_transcript("test123video", fetcher=fake_fetcher)

        assert isinstance(result, TranscriptResult)
        assert result.metadata.video_id == "test123video"
        assert result.transcript.full_text == "Hello"

    def test_propagates_fetch_errors(self) -> None:
        """Should propagate TranscriptFetchError from fetcher."""
        fake_fetcher = FakeTranscriptFetcher(
            error=TranscriptFetchError("test", "Video unavailable")
        )

        with pytest.raises(TranscriptFetchError, match="Video unavailable"):
            fetch_transcript("test12345678", fetcher=fake_fetcher)

    def test_passes_languages_to_fetcher(self) -> None:
        """Should pass language preferences to fetcher."""
        fake_fetcher = FakeTranscriptFetcher()

        fetch_transcript(
            "test12345678",
            languages=["es", "en"],
            fetcher=fake_fetcher,
        )

        assert fake_fetcher.fetch_calls[0][1] == ["es", "en"]
