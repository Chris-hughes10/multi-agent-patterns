"""Tests for agent modules."""

from unittest.mock import MagicMock, patch

from youtube_agent.agents.search_agent import (
    SEARCH_AGENT_INSTRUCTIONS,
    create_search_agent,
)
from youtube_agent.agents.summarize_agent import (
    SUMMARIZE_AGENT_INSTRUCTIONS,
    create_summarize_agent,
    summarize_stored_transcript,
    summarize_text,
)
from youtube_agent.agents.transcript_agent import (
    TRANSCRIPT_AGENT_INSTRUCTIONS,
    create_transcript_agent,
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
)


class TestSearchAgent:
    """Tests for Search Agent."""

    def test_instructions_contain_search_guidance(self) -> None:
        assert "search" in SEARCH_AGENT_INSTRUCTIONS.lower()
        assert "youtube" in SEARCH_AGENT_INSTRUCTIONS.lower()

    @patch("youtube_agent.agents.search_agent.get_chat_client")
    def test_create_search_agent_returns_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_search_agent()
        assert agent.name == "SearchAgent"


class TestTranscriptAgent:
    """Tests for Transcript Agent."""

    def test_instructions_contain_transcript_guidance(self) -> None:
        assert "transcript" in TRANSCRIPT_AGENT_INSTRUCTIONS.lower()
        assert "fetch" in TRANSCRIPT_AGENT_INSTRUCTIONS.lower()

    @patch("youtube_agent.agents.transcript_agent.get_chat_client")
    def test_create_transcript_agent_returns_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_transcript_agent()
        assert agent.name == "TranscriptAgent"

    @patch("youtube_agent.agents.transcript_agent.TranscriptStorage")
    def test_list_stored_transcripts_returns_message_when_empty(
        self, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.list_videos.return_value = []
        mock_storage_class.return_value = mock_storage

        result = list_stored_transcripts()
        assert "No transcripts" in result

    @patch("youtube_agent.agents.transcript_agent.TranscriptStorage")
    def test_lookup_stored_transcript_returns_error_for_missing(
        self, mock_storage_class: MagicMock
    ) -> None:
        mock_storage = MagicMock()
        mock_storage.load.return_value = None
        mock_storage_class.return_value = mock_storage

        result = lookup_stored_transcript("nonexistent123")
        assert "no stored transcript" in result.lower()


class TestSummarizeAgent:
    """Tests for Summarize Agent."""

    def test_instructions_contain_summarize_guidance(self) -> None:
        assert "summar" in SUMMARIZE_AGENT_INSTRUCTIONS.lower()
        assert "transcript" in SUMMARIZE_AGENT_INSTRUCTIONS.lower()

    @patch("youtube_agent.agents.summarize_agent.get_chat_client")
    def test_create_summarize_agent_returns_agent(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        agent = create_summarize_agent()
        assert agent.name == "SummarizeAgent"

    @patch("youtube_agent.agents.summarize_agent.load_transcript")
    def test_summarize_stored_transcript_returns_error_for_missing(
        self, mock_load: MagicMock
    ) -> None:
        mock_load.return_value = None
        result = summarize_stored_transcript("nonexistent123")
        assert "No stored transcript" in result

    @patch("youtube_agent.agents.summarize_agent.TranscriptSummarizer")
    def test_summarize_text_handles_errors(self, mock_summarizer_class: MagicMock) -> None:
        mock_summarizer = MagicMock()
        mock_summarizer.summarize.side_effect = Exception("API error")
        mock_summarizer_class.return_value = mock_summarizer

        result = summarize_text("Some text to summarize")
        assert "Error" in result


class TestAgentTools:
    """Tests for agent tool functions."""

    @patch("youtube_agent.agents.transcript_agent.fetch_transcript")
    def test_fetch_video_transcript_returns_formatted_output(
        self, mock_fetch: MagicMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.metadata.title = "Test Video"
        mock_result.metadata.channel = "Test Channel"
        mock_result.transcript.full_text = "This is the transcript text."
        mock_result.transcript.duration_seconds = 300.0
        mock_fetch.return_value = mock_result

        result = fetch_video_transcript("abc123")
        assert "Test Video" in result
        assert "transcript text" in result

    @patch("youtube_agent.agents.transcript_agent.fetch_transcript")
    def test_fetch_video_transcript_handles_errors(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = Exception("Transcript unavailable")
        result = fetch_video_transcript("abc123")
        assert "Error" in result
