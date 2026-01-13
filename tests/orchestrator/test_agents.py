"""Tests for agent modules."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from youtube_agent_orchestrator.agents.search_agent import create_search_agent
from youtube_agent_orchestrator.agents.summarize_agent import create_summarize_agent
from youtube_agent_orchestrator.agents.transcript_agent import create_transcript_agent
from youtube_agent_orchestrator.agents.writer_agent import create_writer_agent
from youtube_agent_orchestrator.tools.summarize import summarize_stored_transcript, summarize_text
from youtube_agent_orchestrator.tools.youtube import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
)
from youtube_agent_orchestrator.tools.writer import write_markdown_file, write_timestamped_markdown


class TestSearchAgent:
    """Tests for Search Agent factory."""

    @patch("youtube_agent_orchestrator.agents.search_agent.get_chat_client")
    def test_create_search_agent_returns_named_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_search_agent()
        assert agent.name == "SearchAgent"


class TestTranscriptAgent:
    """Tests for Transcript Agent factory."""

    @patch("youtube_agent_orchestrator.agents.transcript_agent.get_chat_client")
    def test_create_transcript_agent_returns_named_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_transcript_agent()
        assert agent.name == "TranscriptAgent"


class TestSummarizeAgent:
    """Tests for Summarize Agent factory."""

    @patch("youtube_agent_orchestrator.agents.summarize_agent.get_chat_client")
    def test_create_summarize_agent_returns_named_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_summarize_agent()
        assert agent.name == "SummarizeAgent"


class TestWriterAgent:
    """Tests for Writer Agent factory."""

    @patch("youtube_agent_orchestrator.agents.writer_agent.get_chat_client")
    def test_create_writer_agent_returns_named_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_writer_agent()
        assert agent.name == "WriterAgent"


class TestTranscriptTools:
    """Tests for transcript tool functions (async)."""

    @patch("youtube_agent_orchestrator.tools.youtube.TranscriptStorage")
    async def test_list_stored_transcripts_returns_message_when_empty(
        self, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.list_videos.return_value = []
        mock_storage_class.return_value = mock_storage

        result = await list_stored_transcripts()
        assert "No transcripts" in result

    @patch("youtube_agent_orchestrator.tools.youtube.TranscriptStorage")
    async def test_lookup_stored_transcript_returns_error_for_missing(
        self, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.load.return_value = None
        mock_storage_class.return_value = mock_storage

        result = await lookup_stored_transcript("nonexistent123")
        assert "no stored transcript" in result.lower()

    @patch("youtube_agent_orchestrator.tools.youtube.get_runtime_config")
    @patch("youtube_agent_orchestrator.tools.youtube.TranscriptStorage")
    @patch("youtube_agent_orchestrator.tools.youtube.fetch_transcript", new_callable=AsyncMock)
    async def test_fetch_video_transcript_returns_formatted_output(
        self, mock_fetch: AsyncMock, mock_storage_class: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.load.return_value = None
        mock_storage_class.return_value = mock_storage
        mock_config.return_value.auto_store_transcripts = False

        mock_result = MagicMock()
        mock_result.metadata.title = "Test Video"
        mock_result.metadata.channel = "Test Channel"
        mock_result.transcript.full_text = "This is the transcript text."
        mock_result.transcript.duration_seconds = 300.0
        mock_fetch.return_value = mock_result

        result = await fetch_video_transcript("dQw4w9WgXcQ")
        assert "Test Video" in result
        assert "transcript text" in result

    @patch("youtube_agent_orchestrator.tools.youtube.TranscriptStorage")
    @patch("youtube_agent_orchestrator.tools.youtube.fetch_transcript")
    async def test_fetch_video_transcript_handles_errors(
        self, mock_fetch: MagicMock, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.load.return_value = None
        mock_storage_class.return_value = mock_storage
        mock_fetch.side_effect = Exception("Transcript unavailable")

        result = await fetch_video_transcript("dQw4w9WgXcQ")
        assert "Error" in result

    @patch("youtube_agent_orchestrator.tools.youtube.TranscriptStorage")
    async def test_fetch_video_transcript_uses_cache(self, mock_storage_class: MagicMock) -> None:
        """Should return cached transcript without calling YouTube API."""
        mock_storage = MagicMock()
        mock_stored = MagicMock()
        mock_stored.metadata.title = "Cached Video"
        mock_stored.transcript.full_text = "Cached transcript text."
        mock_storage.load.return_value = mock_stored
        mock_storage_class.return_value = mock_storage

        result = await fetch_video_transcript("dQw4w9WgXcQ")
        assert "Cached Video" in result
        assert "cache" in result.lower()


class TestSummarizeTools:
    """Tests for summarize tool functions (async)."""

    @patch("youtube_agent_orchestrator.tools.summarize.TranscriptStorage")
    async def test_summarize_stored_transcript_returns_error_for_missing(
        self, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.load.return_value = None
        mock_storage_class.return_value = mock_storage
        result = await summarize_stored_transcript("nonexistent123")
        assert "No stored transcript" in result

    @patch("youtube_agent_orchestrator.tools.summarize.TranscriptSummarizer")
    async def test_summarize_text_handles_errors(self, mock_summarizer_class: MagicMock) -> None:
        mock_summarizer = MagicMock()
        mock_summarizer.summarize = AsyncMock(side_effect=Exception("API error"))
        mock_summarizer_class.return_value = mock_summarizer

        result = await summarize_text("Some text to summarize")
        assert "Error" in result

    @patch("youtube_agent_orchestrator.tools.summarize.TranscriptStorage")
    async def test_summarize_stored_returns_cached_summary(
        self, mock_storage_class: MagicMock
    ) -> None:
        """Should return cached summary without calling LLM."""
        mock_storage = MagicMock()
        mock_stored = MagicMock()
        mock_stored.metadata.title = "Summarized Video"
        mock_stored.summary = "This is a cached summary."
        mock_storage.load.return_value = mock_stored
        mock_storage_class.return_value = mock_storage

        result = await summarize_stored_transcript("test123abcd")
        assert "Summarized Video" in result
        assert "cached" in result.lower()


class TestWriterTools:
    """Tests for writer tool functions (async)."""

    async def test_write_markdown_file_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await write_markdown_file(
                content="# Test\n\nHello world",
                filename="test.md",
                output_dir=tmpdir,
            )
            assert "Successfully wrote" in result
            assert Path(tmpdir, "test.md").exists()
            assert Path(tmpdir, "test.md").read_text() == "# Test\n\nHello world"

    async def test_write_markdown_file_adds_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await write_markdown_file(
                content="# Test",
                filename="notes",
                output_dir=tmpdir,
            )
            assert "Successfully wrote" in result
            assert Path(tmpdir, "notes.md").exists()

    async def test_write_markdown_file_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir, "nested", "dir")
            result = await write_markdown_file(
                content="# Test",
                filename="test.md",
                output_dir=str(subdir),
            )
            assert "Successfully wrote" in result
            assert subdir.exists()

    async def test_write_timestamped_markdown_creates_unique_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await write_timestamped_markdown(
                content="# Notes",
                prefix="research",
                output_dir=tmpdir,
            )
            assert "Successfully wrote" in result
            files = list(Path(tmpdir).glob("research_*.md"))
            assert len(files) == 1
