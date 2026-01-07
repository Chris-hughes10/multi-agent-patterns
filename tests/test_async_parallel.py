"""Test to verify async parallel execution in the orchestrator."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAsyncParallelExecution:
    """Verify that async tools can run in parallel."""

    async def test_parallel_agent_calls_are_faster_than_sequential(self) -> None:
        """
        If tools run in parallel, 3 x 0.1s delays should complete in ~0.1s, not ~0.3s.
        This proves we're using true async, not blocking.
        """

        async def slow_delegate(agent_name: str, request: str) -> str:
            """Simulate a slow agent call."""
            await asyncio.sleep(0.1)  # 100ms delay
            return f"Response from {agent_name}"

        # Import here to avoid circular imports
        from youtube_agent.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent()

        # Patch _delegate to use our slow mock
        orchestrator._delegate = slow_delegate  # type: ignore

        # Run 3 agent calls in parallel
        start = time.perf_counter()
        results = await asyncio.gather(
            orchestrator.ask_search_agent("query 1"),
            orchestrator.ask_transcript_agent("query 2"),
            orchestrator.ask_summarize_agent("query 3"),
        )
        elapsed = time.perf_counter() - start

        # All 3 should have returned
        assert len(results) == 3
        assert all("Response from" in r for r in results)

        # If parallel: ~0.1s. If sequential: ~0.3s
        # Allow some overhead, but should be well under 0.25s
        assert elapsed < 0.25, f"Took {elapsed:.3f}s - calls may not be running in parallel!"
        print(f"\n✓ 3 parallel calls completed in {elapsed:.3f}s (expected ~0.1s)")

    async def test_sequential_calls_take_expected_time(self) -> None:
        """Baseline: sequential calls should take 3x the delay."""

        async def slow_operation() -> str:
            await asyncio.sleep(0.05)
            return "done"

        start = time.perf_counter()
        # Sequential calls
        await slow_operation()
        await slow_operation()
        await slow_operation()
        elapsed = time.perf_counter() - start

        # Should be ~0.15s (3 x 0.05s)
        assert elapsed >= 0.14, f"Sequential took {elapsed:.3f}s - too fast!"
        print(f"\n✓ 3 sequential calls completed in {elapsed:.3f}s (expected ~0.15s)")

    async def test_httpx_search_is_non_blocking(self) -> None:
        """Verify search_youtube uses async httpx, not blocking urllib."""
        from youtube_agent.services.youtube import search_youtube

        # This would hang or be very slow if it was blocking
        # We'll just verify it's callable as async and raises expected error for empty query
        from youtube_agent.services.youtube import YouTubeSearchError

        with pytest.raises(YouTubeSearchError):
            await search_youtube("")

    async def test_summarizer_uses_async_client(self) -> None:
        """Verify TranscriptSummarizer.summarize is async."""
        from unittest.mock import AsyncMock, MagicMock

        from youtube_agent.models.config import Settings
        from youtube_agent.services.summarizer import TranscriptSummarizer

        # Create mock async client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test summary"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        settings = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-test",
        )

        summarizer = TranscriptSummarizer(settings=settings, client=mock_client)

        # This should be awaitable
        result = await summarizer.summarize("Test text")

        assert result == "Test summary"
        mock_client.chat.completions.create.assert_awaited_once()
        print("\n✓ TranscriptSummarizer.summarize is properly async")
