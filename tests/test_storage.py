"""Tests for transcript storage functionality."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from youtube_agent.models.transcript import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
)
from youtube_agent.tools.storage import (
    StoredTranscript,
    TranscriptStorage,
    load_transcript,
    save_transcript,
)


@pytest.fixture
def sample_transcript_result() -> TranscriptResult:
    """Create a sample transcript result for testing."""
    return TranscriptResult(
        metadata=VideoMetadata(
            video_id="test123abcd",
            title="Test Video Title",
            channel="Test Channel",
        ),
        transcript=Transcript(
            video_id="test123abcd",
            segments=[
                TranscriptSegment(text="Hello world", start=0.0, duration=2.0),
                TranscriptSegment(text="This is a test", start=2.0, duration=3.0),
                TranscriptSegment(text="Goodbye", start=5.0, duration=1.5),
            ],
            language="en",
            is_generated=False,
        ),
    )


@pytest.fixture
def temp_storage(tmp_path: Path) -> TranscriptStorage:
    """Create a TranscriptStorage instance with a temporary directory."""
    return TranscriptStorage(storage_dir=tmp_path)


class TestTranscriptStorage:
    """Tests for TranscriptStorage class."""

    def test_save_creates_json_file(
        self,
        temp_storage: TranscriptStorage,
        sample_transcript_result: TranscriptResult,
        tmp_path: Path,
    ) -> None:
        """Saving a transcript should create a JSON file with the video ID as filename."""
        temp_storage.save(sample_transcript_result)

        expected_path = tmp_path / "test123abcd.json"
        assert expected_path.exists()

        # Verify it's valid JSON
        data = json.loads(expected_path.read_text())
        assert data["video_id"] == "test123abcd"

    def test_save_stores_transcript_content(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Saved transcript should contain the full transcript text."""
        stored = temp_storage.save(sample_transcript_result)

        assert stored.transcript.full_text == "Hello world This is a test Goodbye"
        assert len(stored.transcript.segments) == 3

    def test_save_stores_metadata(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Saved transcript should preserve video metadata."""
        stored = temp_storage.save(sample_transcript_result)

        assert stored.metadata.title == "Test Video Title"
        assert stored.metadata.channel == "Test Channel"
        assert stored.metadata.video_id == "test123abcd"

    def test_save_with_summary(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Saving with a summary should include it in the stored data."""
        summary = "This is a test video about greetings."
        stored = temp_storage.save(sample_transcript_result, summary=summary)

        assert stored.summary == summary

    def test_save_sets_timestamps(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Saved transcript should have stored_at and updated_at timestamps."""
        before = datetime.now(UTC)
        stored = temp_storage.save(sample_transcript_result)
        after = datetime.now(UTC)

        assert before <= stored.stored_at <= after
        assert before <= stored.updated_at <= after

    def test_load_returns_stored_transcript(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Loading a saved transcript should return the same data."""
        temp_storage.save(sample_transcript_result, summary="A summary")

        loaded = temp_storage.load("test123abcd")

        assert loaded is not None
        assert loaded.video_id == "test123abcd"
        assert loaded.summary == "A summary"
        assert loaded.transcript.full_text == "Hello world This is a test Goodbye"

    def test_load_returns_none_for_missing(self, temp_storage: TranscriptStorage) -> None:
        """Loading a non-existent video ID should return None."""
        assert temp_storage.load("nonexistent1") is None

    def test_exists_returns_true_for_saved(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """exists() should return True for saved transcripts."""
        temp_storage.save(sample_transcript_result)
        assert temp_storage.exists("test123abcd") is True

    def test_exists_returns_false_for_missing(self, temp_storage: TranscriptStorage) -> None:
        """exists() should return False for non-existent transcripts."""
        assert temp_storage.exists("nonexistent1") is False

    def test_delete_removes_file(
        self,
        temp_storage: TranscriptStorage,
        sample_transcript_result: TranscriptResult,
        tmp_path: Path,
    ) -> None:
        """delete() should remove the transcript file."""
        temp_storage.save(sample_transcript_result)
        assert (tmp_path / "test123abcd.json").exists()

        result = temp_storage.delete("test123abcd")

        assert result is True
        assert not (tmp_path / "test123abcd.json").exists()

    def test_delete_returns_false_for_missing(self, temp_storage: TranscriptStorage) -> None:
        """delete() should return False for non-existent transcripts."""
        assert temp_storage.delete("nonexistent1") is False

    def test_list_videos_returns_all_stored(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """list_videos() should return all stored video IDs."""
        # Save multiple transcripts
        temp_storage.save(sample_transcript_result)

        result2 = TranscriptResult(
            metadata=VideoMetadata(video_id="another1234"),
            transcript=Transcript(
                video_id="another1234",
                segments=[TranscriptSegment(text="Second video", start=0.0, duration=1.0)],
            ),
        )
        temp_storage.save(result2)

        videos = temp_storage.list_videos()

        assert set(videos) == {"test123abcd", "another1234"}

    def test_update_preserves_original_stored_at(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """Updating a transcript should preserve the original stored_at timestamp."""
        import time

        stored1 = temp_storage.save(sample_transcript_result)
        original_stored_at = stored1.stored_at

        time.sleep(0.01)  # Small delay to ensure different timestamp

        stored2 = temp_storage.save(sample_transcript_result, summary="New summary")

        assert stored2.stored_at == original_stored_at
        assert stored2.updated_at > stored2.stored_at

    def test_update_summary_modifies_only_summary(
        self, temp_storage: TranscriptStorage, sample_transcript_result: TranscriptResult
    ) -> None:
        """update_summary() should only change the summary field."""
        temp_storage.save(sample_transcript_result, summary="Original")

        updated = temp_storage.update_summary("test123abcd", "Updated summary")

        assert updated is not None
        assert updated.summary == "Updated summary"
        assert updated.transcript.full_text == "Hello world This is a test Goodbye"


class TestConvenienceFunctions:
    """Tests for save_transcript and load_transcript convenience functions."""

    def test_save_and_load_round_trip(
        self, sample_transcript_result: TranscriptResult, tmp_path: Path
    ) -> None:
        """save_transcript and load_transcript should round-trip data correctly."""
        storage = TranscriptStorage(storage_dir=tmp_path)

        save_transcript(sample_transcript_result, summary="Test summary", storage=storage)
        loaded = load_transcript("test123abcd", storage=storage)

        assert loaded is not None
        assert loaded.summary == "Test summary"
        assert loaded.video_id == "test123abcd"


class TestStoredTranscriptModel:
    """Tests for StoredTranscript pydantic model."""

    def test_serialization_round_trip(self) -> None:
        """StoredTranscript should serialize and deserialize correctly."""
        now = datetime.now(UTC)
        stored = StoredTranscript(
            video_id="test123abcd",
            transcript=Transcript(
                video_id="test123abcd",
                segments=[TranscriptSegment(text="Test", start=0.0, duration=1.0)],
            ),
            metadata=VideoMetadata(video_id="test123abcd", title="Test"),
            summary="A summary",
            stored_at=now,
            updated_at=now,
        )

        json_str = stored.model_dump_json()
        restored = StoredTranscript.model_validate_json(json_str)

        assert restored.video_id == stored.video_id
        assert restored.summary == stored.summary
        assert restored.transcript.full_text == stored.transcript.full_text
