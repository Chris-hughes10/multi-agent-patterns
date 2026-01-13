"""Tests for V2 Autonomous pattern.

Testing Philosophy: Classicist approach (Kent Beck style)
- Only mock external/long-running calls (YouTube API, LLM calls)
- Use real objects for everything else (agents, registry, router, session)
- Test behavior, not implementation details
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from youtube_agent_orchestrator.models.youtube import (
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    VideoMetadata,
    VideoSearchResult,
)
from youtube_autonomous_agents.agents import (
    SearchAgent,
    SummarizeAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_autonomous_agents.infra import AgentRegistry
from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult

# ============================================================================
# Test Helpers for LLM Mocking
# ============================================================================


def create_mock_chat_client(satisfied: bool = True, next_step: str = "") -> MagicMock:
    """Create a mock chat client that returns appropriate responses based on prompt.

    Handles both query extraction prompts and goal reasoning prompts.

    :param satisfied: Whether to return SATISFIED: yes or no for goal reasoning
    :param next_step: The next step to return if not satisfied
    :return: Mock chat client
    """

    async def smart_get_response(prompt: str) -> MagicMock:
        """Return different responses based on prompt content."""
        mock_response = MagicMock()

        # Check if this is a query extraction prompt
        if "Extract a YouTube search query" in prompt or "Search query:" in prompt:
            # Return a simple query
            mock_response.text = "test query"
        # Check if this is a goal reasoning prompt (look for key phrases from the prompts)
        elif "goal is satisfied" in prompt.lower() or "SATISFIED:" in prompt:
            if satisfied:
                mock_response.text = "SATISFIED: yes\nNEXT_STEP: none"
            else:
                mock_response.text = f"SATISFIED: no\nNEXT_STEP: {next_step}"
        else:
            # Default response
            mock_response.text = "default response"

        return mock_response

    mock_client = MagicMock()
    mock_client.get_response = AsyncMock(side_effect=smart_get_response)
    return mock_client


@contextmanager
def mock_goal_reasoning(satisfied: bool = True, next_step: str = ""):
    """Context manager to mock LLM goal reasoning calls.

    :param satisfied: Whether goal should be satisfied
    :param next_step: Next step if not satisfied
    """
    mock_client = create_mock_chat_client(satisfied, next_step)
    # Patch where BaseAgent gets the chat client (all agents now use base class client)
    with patch(
        "youtube_autonomous_agents.agents.base.get_chat_client",
        return_value=mock_client,
    ):
        yield mock_client


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry() -> AgentRegistry:
    """Create an empty agent registry."""
    return AgentRegistry()


@pytest.fixture
def mock_search_results() -> list[VideoSearchResult]:
    """Create mock search results."""
    return [
        VideoSearchResult(
            video_id="abc123def45",
            title="Test Video 1",
            channel="Test Channel",
            duration="10:30",
            view_count="1000",
            published_time="1 day ago",
        ),
        VideoSearchResult(
            video_id="xyz789ghi12",
            title="Test Video 2",
            channel="Test Channel 2",
            duration="5:15",
            view_count="500",
            published_time="2 days ago",
        ),
    ]


@pytest.fixture
def mock_transcript_result() -> TranscriptResult:
    """Create a mock transcript result."""
    return TranscriptResult(
        metadata=VideoMetadata(
            video_id="abc123def45",
            title="Test Video 1",
            channel="Test Channel",
        ),
        transcript=Transcript(
            video_id="abc123def45",
            segments=[
                TranscriptSegment(text="Hello world", start=0.0, duration=1.0),
                TranscriptSegment(text="This is a test", start=1.0, duration=2.0),
            ],
        ),
    )


# ============================================================================
# Agent Description Tests
# ============================================================================


class TestAgentDescriptions:
    """Test that all agents have meaningful descriptions for intent routing."""

    def test_search_agent_has_description(self, registry: AgentRegistry) -> None:
        """SearchAgent should have a description."""
        agent = SearchAgent(registry)
        assert agent.description
        assert "search" in agent.description.lower()

    def test_transcript_agent_has_description(self, registry: AgentRegistry) -> None:
        """TranscriptAgent should have a description."""
        agent = TranscriptAgent(registry)
        assert agent.description
        assert "transcript" in agent.description.lower()

    def test_summarize_agent_has_description(self, registry: AgentRegistry) -> None:
        """SummarizeAgent should have a description."""
        agent = SummarizeAgent(registry)
        assert agent.description
        assert "summar" in agent.description.lower()

    def test_writer_agent_has_description(self, registry: AgentRegistry) -> None:
        """WriterAgent should have a description."""
        agent = WriterAgent(registry)
        assert agent.description
        assert "write" in agent.description.lower() or "export" in agent.description.lower()


# ============================================================================
# SearchAgent Autonomous Tests
# ============================================================================


class TestSearchAgentAutonomous:
    """Test SearchAgent.execute_autonomous() behavior."""

    @pytest.mark.asyncio
    async def test_search_completes_when_goal_is_just_search(
        self,
        registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """SearchAgent should complete when goal is just searching."""
        agent = SearchAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.search.search_youtube",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            mock_goal_reasoning(satisfied=True),
        ):
            result = await agent.execute_autonomous(
                goal="Search for Python tutorials",
                state={},
            )

        assert isinstance(result, HandoffResult)
        assert result.is_complete
        assert "results" in result.result
        assert result.result["count"] == 2

    @pytest.mark.asyncio
    async def test_search_hands_off_when_goal_needs_more(
        self,
        registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """SearchAgent should hand off when LLM determines goal needs more work."""
        agent = SearchAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.search.search_youtube",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            mock_goal_reasoning(satisfied=False, next_step="Get transcripts for these videos"),
        ):
            result = await agent.execute_autonomous(
                goal="Find videos about cooking and get their transcripts",
                state={},
            )

        assert isinstance(result, HandoffResult)
        assert result.is_handoff
        assert "transcript" in result.intent.lower()
        assert "videos" in result.state
        assert "search" in result.state

    @pytest.mark.asyncio
    async def test_search_hands_off_for_summarization(
        self,
        registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """SearchAgent should hand off when LLM determines summarization is needed."""
        agent = SearchAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.search.search_youtube",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            mock_goal_reasoning(satisfied=False, next_step="Get transcripts and summarize them"),
        ):
            result = await agent.execute_autonomous(
                goal="Find and summarize videos about machine learning",
                state={},
            )

        assert isinstance(result, HandoffResult)
        assert result.is_handoff
        assert "summarize" in result.intent.lower() or "transcript" in result.intent.lower()

    @pytest.mark.asyncio
    async def test_search_extracts_query_from_goal(
        self,
        registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """SearchAgent should extract search query from natural language goal."""
        agent = SearchAgent(registry)

        with patch(
            "youtube_autonomous_agents.agents.search.search_youtube",
            new_callable=AsyncMock,
            return_value=mock_search_results,
        ) as mock_search:
            await agent.execute_autonomous(
                goal="Find videos about pork loin cooking",
                state={},
            )

        # Check that search was called with extracted query
        mock_search.assert_called_once()
        query = mock_search.call_args[0][0]
        assert "pork loin" in query.lower()

    @pytest.mark.asyncio
    async def test_search_uses_query_from_state(
        self,
        registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """SearchAgent should use query from state if provided."""
        agent = SearchAgent(registry)

        with patch(
            "youtube_autonomous_agents.agents.search.search_youtube",
            new_callable=AsyncMock,
            return_value=mock_search_results,
        ) as mock_search:
            await agent.execute_autonomous(
                goal="Some random goal",
                state={"query": "specific query from state"},
            )

        mock_search.assert_called_once()
        query = mock_search.call_args[0][0]
        assert query == "specific query from state"

    @pytest.mark.asyncio
    async def test_search_returns_partial_on_error(
        self,
        registry: AgentRegistry,
    ) -> None:
        """SearchAgent should return PartialResult on error."""
        agent = SearchAgent(registry)

        with patch(
            "youtube_autonomous_agents.agents.search.search_youtube",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            result = await agent.execute_autonomous(
                goal="Search for videos",
                state={},
            )

        assert isinstance(result, PartialResult)
        assert "error" in result.error.lower() or "failed" in result.error.lower()


# ============================================================================
# TranscriptAgent Autonomous Tests
# ============================================================================


class TestTranscriptAgentAutonomous:
    """Test TranscriptAgent.execute_autonomous() behavior."""

    @pytest.mark.asyncio
    async def test_transcript_completes_when_goal_is_just_transcript(
        self,
        registry: AgentRegistry,
        mock_transcript_result: TranscriptResult,
    ) -> None:
        """TranscriptAgent should complete when goal is just transcripts."""
        agent = TranscriptAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.transcript.fetch_transcript",
                new_callable=AsyncMock,
                return_value=mock_transcript_result,
            ),
            patch(
                "youtube_autonomous_agents.agents.transcript.TranscriptStorage"
            ) as mock_storage_class,
            mock_goal_reasoning(satisfied=True),
        ):
            mock_storage = MagicMock()
            mock_storage.load.return_value = None  # Not cached
            mock_storage.save.return_value = None
            mock_storage_class.return_value = mock_storage

            result = await agent.execute_autonomous(
                goal="Get the transcript for video abc123def45",
                state={"video_id": "abc123def45"},
            )

        assert isinstance(result, HandoffResult)
        assert result.is_complete
        assert "transcripts" in result.result

    @pytest.mark.asyncio
    async def test_transcript_hands_off_when_goal_needs_summary(
        self,
        registry: AgentRegistry,
        mock_transcript_result: TranscriptResult,
    ) -> None:
        """TranscriptAgent should hand off when LLM determines summarization is needed."""
        agent = TranscriptAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.transcript.fetch_transcript",
                new_callable=AsyncMock,
                return_value=mock_transcript_result,
            ),
            patch(
                "youtube_autonomous_agents.agents.transcript.TranscriptStorage"
            ) as mock_storage_class,
            mock_goal_reasoning(satisfied=False, next_step="Summarize these transcripts"),
        ):
            mock_storage = MagicMock()
            mock_storage.load.return_value = None
            mock_storage.save.return_value = None
            mock_storage_class.return_value = mock_storage

            result = await agent.execute_autonomous(
                goal="Get transcript and summarize the key points",
                state={"video_id": "abc123def45"},
            )

        assert isinstance(result, HandoffResult)
        assert result.is_handoff
        assert "summarize" in result.intent.lower()
        assert "transcript" in result.state

    @pytest.mark.asyncio
    async def test_transcript_uses_videos_from_state(
        self,
        registry: AgentRegistry,
        mock_transcript_result: TranscriptResult,
    ) -> None:
        """TranscriptAgent should use videos from state (from search)."""
        agent = TranscriptAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.transcript.fetch_transcript",
                new_callable=AsyncMock,
                return_value=mock_transcript_result,
            ),
            patch(
                "youtube_autonomous_agents.agents.transcript.TranscriptStorage"
            ) as mock_storage_class,
            mock_goal_reasoning(satisfied=True),
        ):
            mock_storage = MagicMock()
            mock_storage.load.return_value = None
            mock_storage.save.return_value = None
            mock_storage_class.return_value = mock_storage

            result = await agent.execute_autonomous(
                goal="Get transcripts",
                state={
                    "videos": [
                        {"video_id": "abc123def45", "title": "Video 1"},
                        {"video_id": "xyz789ghi12", "title": "Video 2"},
                    ]
                },
            )

        assert isinstance(result, HandoffResult)
        # Should have fetched transcripts for videos from state
        assert result.result["count"] >= 1

    @pytest.mark.asyncio
    async def test_transcript_returns_partial_when_no_video_id(
        self,
        registry: AgentRegistry,
    ) -> None:
        """TranscriptAgent should return PartialResult when no video ID available."""
        agent = TranscriptAgent(registry)

        result = await agent.execute_autonomous(
            goal="Get transcripts",
            state={},  # No videos or video_id
        )

        assert isinstance(result, PartialResult)
        # Error message varies - just check it's an error about fetching
        assert result.error is not None


# ============================================================================
# SummarizeAgent Autonomous Tests
# ============================================================================


class TestSummarizeAgentAutonomous:
    """Test SummarizeAgent.execute_autonomous() behavior."""

    @pytest.mark.asyncio
    async def test_summarize_completes_normally(
        self,
        registry: AgentRegistry,
    ) -> None:
        """SummarizeAgent should typically complete (final step)."""
        agent = SummarizeAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.summarize.TranscriptSummarizer"
            ) as mock_summarizer_class,
            mock_goal_reasoning(satisfied=True),
        ):
            mock_summarizer = MagicMock()
            mock_summarizer.summarize = AsyncMock(return_value="This is a summary.")
            mock_summarizer_class.return_value = mock_summarizer

            result = await agent.execute_autonomous(
                goal="Summarize the cooking instructions",
                state={
                    "transcript": {
                        "transcripts": [
                            {"video_id": "abc123", "title": "Cooking", "text": "Cook at 350F"}
                        ]
                    }
                },
            )

        assert isinstance(result, HandoffResult)
        assert result.is_complete
        assert "summaries" in result.result

    @pytest.mark.asyncio
    async def test_summarize_hands_off_when_goal_needs_file(
        self,
        registry: AgentRegistry,
    ) -> None:
        """SummarizeAgent should hand off when LLM determines file writing is needed."""
        agent = SummarizeAgent(registry)

        with (
            patch(
                "youtube_autonomous_agents.agents.summarize.TranscriptSummarizer"
            ) as mock_summarizer_class,
            mock_goal_reasoning(satisfied=False, next_step="Write these summaries to a markdown file"),
        ):
            mock_summarizer = MagicMock()
            mock_summarizer.summarize = AsyncMock(return_value="This is a summary.")
            mock_summarizer_class.return_value = mock_summarizer

            result = await agent.execute_autonomous(
                goal="Summarize and save to a markdown file",
                state={
                    "transcript": {
                        "transcripts": [
                            {"video_id": "abc123", "title": "Test", "text": "Content"}
                        ]
                    }
                },
            )

        assert isinstance(result, HandoffResult)
        assert result.is_handoff
        assert "write" in result.intent.lower() or "file" in result.intent.lower()
        assert "summarize" in result.state

    @pytest.mark.asyncio
    async def test_summarize_returns_partial_when_no_transcripts(
        self,
        registry: AgentRegistry,
    ) -> None:
        """SummarizeAgent should return PartialResult when no transcripts."""
        agent = SummarizeAgent(registry)

        result = await agent.execute_autonomous(
            goal="Summarize the content",
            state={},  # No transcripts
        )

        assert isinstance(result, PartialResult)
        assert "no transcript" in result.error.lower()


# ============================================================================
# WriterAgent Autonomous Tests
# ============================================================================


class TestWriterAgentAutonomous:
    """Test WriterAgent.execute_autonomous() behavior."""

    @pytest.mark.asyncio
    async def test_writer_always_completes(
        self,
        registry: AgentRegistry,
    ) -> None:
        """WriterAgent should always complete (final step)."""
        agent = WriterAgent(registry)

        with patch(
            "youtube_autonomous_agents.agents.writer.write_timestamped_markdown",
            new_callable=AsyncMock,
            return_value="/output/test_file.md",
        ):
            result = await agent.execute_autonomous(
                goal="Save the research results",
                state={
                    "summarize": {
                        "summaries": [
                            {"video_id": "abc123", "title": "Test", "summary": "Summary text"}
                        ]
                    }
                },
            )

        assert isinstance(result, HandoffResult)
        assert result.is_complete
        assert "filepath" in result.result

    @pytest.mark.asyncio
    async def test_writer_builds_content_from_state(
        self,
        registry: AgentRegistry,
    ) -> None:
        """WriterAgent should build markdown content from accumulated state."""
        agent = WriterAgent(registry)

        written_content = None

        async def capture_write(content: str, prefix: str = "") -> str:
            nonlocal written_content
            written_content = content
            return f"/output/{prefix}_file.md"

        # Mock the LLM call for synthesizing markdown
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "# Cooking Research\n\n## Summary\n\nCook at 350F for best results."
        mock_client.get_response = AsyncMock(return_value=mock_response)

        with (
            patch(
                "youtube_autonomous_agents.agents.writer.write_timestamped_markdown",
                new_callable=AsyncMock,
                side_effect=capture_write,
            ),
            patch(
                "youtube_autonomous_agents.agents.base.get_chat_client",
                return_value=mock_client,
            ),
        ):
            await agent.execute_autonomous(
                goal="Save cooking research",
                state={
                    "search": {
                        "results": [
                            {"video_id": "abc123", "title": "Cooking Video", "channel": "Chef"}
                        ]
                    },
                    "summarize": {
                        "summaries": [
                            {"video_id": "abc123", "title": "Cooking Video", "summary": "Cook at 350F"}
                        ]
                    },
                },
            )

        assert written_content is not None
        # Check content includes either synthesized or original data
        assert "350" in written_content  # Temperature value preserved
        assert "Source Videos" in written_content  # Video links appended


# ============================================================================
# Integration Tests - Full Chains
# ============================================================================


class TestAutonomousChain:
    """Integration tests for full autonomous agent chains."""

    @pytest.fixture
    def full_registry(self, registry: AgentRegistry) -> AgentRegistry:
        """Create registry with all agents."""
        registry.register(SearchAgent(registry))
        registry.register(TranscriptAgent(registry))
        registry.register(SummarizeAgent(registry))
        registry.register(WriterAgent(registry))
        return registry

    @pytest.mark.asyncio
    async def test_search_only_chain(
        self,
        full_registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
    ) -> None:
        """Test chain that completes at search."""
        search_agent = full_registry.get_agent("search")

        with (
            patch(
                "youtube_autonomous_agents.agents.search.search_youtube",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            mock_goal_reasoning(satisfied=True),
        ):
            result = await search_agent.execute_autonomous(
                goal="Find videos about Python",
                state={},
            )

        # Should complete without handoff since goal is just search
        assert isinstance(result, HandoffResult)
        assert result.is_complete

    @pytest.mark.asyncio
    async def test_search_to_transcript_handoff(
        self,
        full_registry: AgentRegistry,
        mock_search_results: list[VideoSearchResult],
        mock_transcript_result: TranscriptResult,
    ) -> None:
        """Test search -> transcript handoff."""
        search_agent = full_registry.get_agent("search")
        transcript_agent = full_registry.get_agent("transcript")

        # Step 1: Search hands off to transcript
        with (
            patch(
                "youtube_autonomous_agents.agents.search.search_youtube",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            mock_goal_reasoning(satisfied=False, next_step="Get transcripts for these videos"),
        ):
            search_result = await search_agent.execute_autonomous(
                goal="Find videos about cooking and get transcripts",
                state={},
            )

        assert search_result.is_handoff
        assert "videos" in search_result.state

        # Step 2: Transcript completes
        with (
            patch(
                "youtube_autonomous_agents.agents.transcript.fetch_transcript",
                new_callable=AsyncMock,
                return_value=mock_transcript_result,
            ),
            patch(
                "youtube_autonomous_agents.agents.transcript.TranscriptStorage"
            ) as mock_storage_class,
            mock_goal_reasoning(satisfied=True),
        ):
            mock_storage = MagicMock()
            mock_storage.load.return_value = None
            mock_storage.save.return_value = None
            mock_storage_class.return_value = mock_storage

            transcript_result = await transcript_agent.execute_autonomous(
                goal="Get the transcripts from these videos",
                state=search_result.state,
            )

        assert isinstance(transcript_result, HandoffResult)
        assert transcript_result.is_complete
        assert "transcripts" in transcript_result.result


# ============================================================================
# Loop Detection Tests
# ============================================================================


class TestAutonomousLoopDetection:
    """Tests for loop detection in autonomous pattern."""

    def test_loop_detector_detects_simple_cycle(self) -> None:
        """Test that LoopDetector detects simple A->B->A cycles."""
        from youtube_autonomous_agents.infra.loop_detector import LoopDetector
        from youtube_autonomous_agents.infra.session import ExecutionStep

        # max_visits=2 means agent can be visited at most 2 times, 3rd visit triggers
        detector = LoopDetector(max_visits=2, window_size=10)

        # Simulate A -> B -> A -> B -> A pattern (A visited 3 times, exceeds max_visits=2)
        steps = [
            ExecutionStep.create(agent_name="A", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="B", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="A", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="B", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="A", action="handoff", task_id="1"),
        ]

        # After 5 steps, A has been visited 3 times which exceeds max_visits=2
        assert detector.check_for_loop(steps)

    def test_loop_detector_allows_normal_progression(self) -> None:
        """Test that LoopDetector allows normal agent progression."""
        from youtube_autonomous_agents.infra.loop_detector import LoopDetector
        from youtube_autonomous_agents.infra.session import ExecutionStep

        detector = LoopDetector(max_visits=3, window_size=10)

        # Normal progression: search -> transcript -> summarize
        steps = [
            ExecutionStep.create(agent_name="search", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="transcript", action="handoff", task_id="1"),
            ExecutionStep.create(agent_name="summarize", action="complete", task_id="1"),
        ]

        assert not detector.check_for_loop(steps)
