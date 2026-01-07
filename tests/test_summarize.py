"""Tests for transcript summarization functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from youtube_agent.models.transcript import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
)
from youtube_agent.tools.summarize import (
    SummarizationError,
    TranscriptSummarizer,
    summarize_transcript,
)


@pytest.fixture
def sample_transcript_result() -> TranscriptResult:
    """Create a sample transcript result for testing."""
    return TranscriptResult(
        metadata=VideoMetadata(
            video_id="test123abcd",
            title="Introduction to Python Programming",
            channel="Code Academy",
        ),
        transcript=Transcript(
            video_id="test123abcd",
            segments=[
                TranscriptSegment(
                    text="Welcome to this Python tutorial.",
                    start=0.0,
                    duration=3.0,
                ),
                TranscriptSegment(
                    text="Today we will learn about variables and data types.",
                    start=3.0,
                    duration=4.0,
                ),
                TranscriptSegment(
                    text="Variables are containers for storing data values.",
                    start=7.0,
                    duration=3.5,
                ),
                TranscriptSegment(
                    text="Python has several built-in data types including strings, integers, and floats.",
                    start=10.5,
                    duration=5.0,
                ),
                TranscriptSegment(
                    text="Let's start by creating our first variable.",
                    start=15.5,
                    duration=3.0,
                ),
            ],
            language="en",
            is_generated=False,
        ),
    )


class TestTranscriptSummarizer:
    """Tests for TranscriptSummarizer class."""

    def test_raises_error_when_not_configured(self) -> None:
        """Should raise SummarizationError when Azure OpenAI is not configured."""
        from youtube_agent.models.config import Settings

        # Create settings explicitly with no Azure config
        unconfigured_settings = Settings(
            azure_openai_endpoint=None,
            azure_openai_api_key=None,
            azure_openai_deployment=None,
            _env_file=None,  # Don't read from .env
        )

        with pytest.raises(SummarizationError, match="Azure OpenAI not configured"):
            TranscriptSummarizer(settings=unconfigured_settings)

    def test_default_system_prompt_is_set(self) -> None:
        """Should have a reasonable default system prompt."""
        prompt = TranscriptSummarizer.DEFAULT_SYSTEM_PROMPT.lower()
        assert "summariz" in prompt  # matches "summarize" or "summarizing"
        assert "video" in prompt


class TestSummarizationError:
    """Tests for SummarizationError exception."""

    def test_error_message_includes_reason(self) -> None:
        """SummarizationError should include the reason in the message."""
        error = SummarizationError("API rate limit exceeded")
        assert "API rate limit exceeded" in str(error)
        assert "Summarization failed" in str(error)

    def test_error_stores_reason(self) -> None:
        """SummarizationError should store the reason as an attribute."""
        error = SummarizationError("Connection timeout")
        assert error.reason == "Connection timeout"


@pytest.mark.integration
class TestSummarizationIntegration:
    """Integration tests that require Azure OpenAI configuration.

    These tests verify the full summarization pipeline works with a real LLM.
    They require:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_DEPLOYMENT

    to be set in the environment.
    """

    async def test_summarize_produces_meaningful_output(
        self, sample_transcript_result: TranscriptResult
    ) -> None:
        """Should produce a summary that reflects the transcript content."""
        try:
            summarizer = TranscriptSummarizer()
        except SummarizationError:
            pytest.skip("Azure OpenAI not configured")

        summary = await summarizer.summarize_result(sample_transcript_result)

        # Summary should be non-empty
        assert len(summary) > 50

        # Summary should reference the main topic (Python)
        summary_lower = summary.lower()
        assert any(
            keyword in summary_lower
            for keyword in ["python", "programming", "variable", "tutorial"]
        ), f"Summary should mention the topic. Got: {summary}"

    async def test_summarize_with_custom_prompt(
        self, sample_transcript_result: TranscriptResult
    ) -> None:
        """Should respect custom system prompts."""
        try:
            summarizer = TranscriptSummarizer()
        except SummarizationError:
            pytest.skip("Azure OpenAI not configured")

        custom_prompt = "Summarize this transcript in exactly 3 bullet points."
        summary = await summarizer.summarize_result(
            sample_transcript_result, system_prompt=custom_prompt
        )

        # Should have produced some output
        assert len(summary) > 20

    async def test_summarize_includes_video_title_context(
        self, sample_transcript_result: TranscriptResult
    ) -> None:
        """Should use video title for better context."""
        try:
            summarizer = TranscriptSummarizer()
        except SummarizationError:
            pytest.skip("Azure OpenAI not configured")

        # The summarizer should include title in context
        summary = await summarizer.summarize(
            transcript_text=sample_transcript_result.transcript.full_text,
            video_title="Introduction to Python Programming",
        )

        assert len(summary) > 50

    async def test_summarize_transcript_saves_to_storage(
        self, sample_transcript_result: TranscriptResult, tmp_path
    ) -> None:
        """summarize_transcript should save the result when save=True."""
        try:
            summarizer = TranscriptSummarizer()
        except SummarizationError:
            pytest.skip("Azure OpenAI not configured")

        from youtube_agent.services.storage import TranscriptStorage

        storage = TranscriptStorage(storage_dir=tmp_path)

        result = await summarize_transcript(
            sample_transcript_result,
            save=True,
            storage=storage,
            summarizer=summarizer,
        )

        # Should have saved
        assert (tmp_path / "test123abcd.json").exists()
        assert result.summary is not None
        assert len(result.summary) > 50

    async def test_summarize_transcript_without_saving(
        self, sample_transcript_result: TranscriptResult, tmp_path
    ) -> None:
        """summarize_transcript should not save when save=False."""
        try:
            summarizer = TranscriptSummarizer()
        except SummarizationError:
            pytest.skip("Azure OpenAI not configured")

        from youtube_agent.services.storage import TranscriptStorage

        storage = TranscriptStorage(storage_dir=tmp_path)

        result = await summarize_transcript(
            sample_transcript_result,
            save=False,
            storage=storage,
            summarizer=summarizer,
        )

        # Should NOT have saved
        assert not (tmp_path / "test123abcd.json").exists()
        # But should still have a summary
        assert result.summary is not None


class TestMockedSummarization:
    """Tests using a mock client to verify behavior without API calls (async)."""

    async def test_summarize_passes_correct_messages_to_client(
        self, sample_transcript_result: TranscriptResult
    ) -> None:
        """Should format messages correctly for the Azure OpenAI client."""
        from youtube_agent.models.config import Settings

        # Create mock async client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a test summary."
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Create settings that appear configured
        settings = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-test",
        )

        summarizer = TranscriptSummarizer(settings=settings, client=mock_client)
        summary = await summarizer.summarize_result(sample_transcript_result)

        # Verify the client was called correctly
        mock_client.chat.completions.create.assert_called_once()
        call_args = mock_client.chat.completions.create.call_args

        assert call_args.kwargs["model"] == "gpt-test"
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Python" in messages[1]["content"]  # Should include title
        assert "Welcome to this Python tutorial" in messages[1]["content"]

        assert summary == "This is a test summary."

    async def test_summarize_handles_api_errors(
        self, sample_transcript_result: TranscriptResult
    ) -> None:
        """Should wrap API errors in SummarizationError."""
        from youtube_agent.models.config import Settings

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

        settings = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-test",
        )

        summarizer = TranscriptSummarizer(settings=settings, client=mock_client)

        with pytest.raises(SummarizationError, match="API Error"):
            await summarizer.summarize_result(sample_transcript_result)
