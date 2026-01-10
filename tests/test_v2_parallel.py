"""Tests for V2 Parallel fan-out/fan-in functionality.

Testing Philosophy: Classicist approach
- Mock external calls (LLM, YouTube API)
- Test real parallel execution with asyncio
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from youtube_autonomous_agents.agents.synthesizer import RequestAnalysis, SynthesizerAgent
from youtube_autonomous_agents.infra import AgentRegistry
from youtube_autonomous_agents.models.handoff import HandoffResult

# ============================================================================
# RequestAnalysis Tests
# ============================================================================


class TestRequestAnalysis:
    """Tests for the RequestAnalysis dataclass."""

    def test_sequential_factory(self):
        """Test creating a sequential analysis."""
        analysis = RequestAnalysis.sequential("search for videos")
        assert analysis.has_parallelism is False
        assert analysis.first_intent == "search for videos"
        assert analysis.parallel_intents == []
        assert analysis.join_intent is None

    def test_parallel_factory(self):
        """Test creating a parallel analysis."""
        analysis = RequestAnalysis.parallel(
            intents=["search channel A", "search channel B"],
            join_intent="combine results",
        )
        assert analysis.has_parallelism is True
        assert analysis.parallel_intents == ["search channel A", "search channel B"]
        assert analysis.join_intent == "combine results"
        assert analysis.first_intent is None


# ============================================================================
# HandoffResult.fan_out Tests
# ============================================================================


class TestHandoffResultFanOut:
    """Tests for the fan_out action in HandoffResult."""

    def test_fan_out_factory(self):
        """Test creating a fan_out result."""
        result = HandoffResult.fan_out(
            intents=["task A", "task B"],
            join_intent="combine results",
            state={"key": "value"},
        )
        assert result.action == "fan_out"
        assert result.intents == ["task A", "task B"]
        assert result.join_intent == "combine results"
        assert result.state == {"key": "value"}
        assert result.is_fan_out is True
        assert result.is_handoff is False
        assert result.is_complete is False

    def test_fan_out_requires_at_least_two_intents(self):
        """Test that fan_out requires at least 2 intents."""
        with pytest.raises(ValueError, match="at least 2 intents"):
            HandoffResult.fan_out(
                intents=["only one"],
                join_intent="combine",
            )

    def test_fan_out_requires_join_intent(self):
        """Test that fan_out requires a join_intent."""
        with pytest.raises(ValueError, match="requires a join_intent"):
            HandoffResult(
                action="fan_out",
                intents=["task A", "task B"],
                join_intent=None,
            )

    def test_fan_out_with_empty_state(self):
        """Test fan_out with default empty state."""
        result = HandoffResult.fan_out(
            intents=["task A", "task B"],
            join_intent="combine",
        )
        assert result.state == {}


# ============================================================================
# Synthesizer._analyze_request Tests
# ============================================================================


class TestAnalyzeRequest:
    """Tests for parallelism detection in user requests."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry with agents."""
        registry = MagicMock(spec=AgentRegistry)

        # Create mock agents
        search_agent = MagicMock()
        search_agent.name = "search"
        search_agent.description = "Searches YouTube for videos"
        search_agent.capabilities = ["youtube_search"]

        transcript_agent = MagicMock()
        transcript_agent.name = "transcript"
        transcript_agent.description = "Fetches video transcripts"
        transcript_agent.capabilities = ["transcript_fetch"]

        registry.all_agents.return_value = [search_agent, transcript_agent]
        return registry

    @pytest.fixture
    def synthesizer(self, mock_registry):
        """Create a synthesizer with mock dependencies."""
        mock_client = MagicMock()
        return SynthesizerAgent(registry=mock_registry, client=mock_client)

    @pytest.mark.asyncio
    async def test_analyze_detects_parallel_searches(self, synthesizer):
        """Test that LLM correctly identifies parallel search requests."""
        # Mock LLM response indicating parallelism
        mock_response = MagicMock()
        mock_response.text = """{
            "has_parallelism": true,
            "parallel_intents": ["Search chuds bbq for pork loin", "Search fork and embers for pork loin"],
            "join_intent": "Combine search results and continue",
            "reasoning": "Two independent channel searches"
        }"""
        synthesizer._client.get_response = AsyncMock(return_value=mock_response)

        analysis = await synthesizer._analyze_request(
            "Search chuds bbq and fork and embers for pork loin recipes"
        )

        assert analysis.has_parallelism is True
        assert len(analysis.parallel_intents) == 2
        assert "chuds bbq" in analysis.parallel_intents[0].lower()
        assert analysis.join_intent is not None

    @pytest.mark.asyncio
    async def test_analyze_detects_sequential_request(self, synthesizer):
        """Test that LLM correctly identifies sequential requests."""
        # Mock LLM response indicating no parallelism
        mock_response = MagicMock()
        mock_response.text = """{
            "has_parallelism": false,
            "parallel_intents": null,
            "join_intent": null,
            "reasoning": "Sequential flow: search then transcripts then summarize"
        }"""
        synthesizer._client.get_response = AsyncMock(return_value=mock_response)

        analysis = await synthesizer._analyze_request(
            "Search for videos, get transcripts, and summarize"
        )

        assert analysis.has_parallelism is False
        assert analysis.parallel_intents == []

    @pytest.mark.asyncio
    async def test_analyze_handles_malformed_response(self, synthesizer):
        """Test graceful fallback when LLM returns malformed JSON."""
        mock_response = MagicMock()
        mock_response.text = "not valid json"
        synthesizer._client.get_response = AsyncMock(return_value=mock_response)

        analysis = await synthesizer._analyze_request("some request")

        # Should fall back to sequential
        assert analysis.has_parallelism is False

    @pytest.mark.asyncio
    async def test_analyze_handles_code_block_response(self, synthesizer):
        """Test parsing JSON wrapped in markdown code blocks."""
        mock_response = MagicMock()
        mock_response.text = """```json
{
    "has_parallelism": true,
    "parallel_intents": ["task A", "task B"],
    "join_intent": "combine",
    "reasoning": "test"
}
```"""
        synthesizer._client.get_response = AsyncMock(return_value=mock_response)

        analysis = await synthesizer._analyze_request("parallel request")

        assert analysis.has_parallelism is True
        assert len(analysis.parallel_intents) == 2


# ============================================================================
# SelfSelectingPool Fan-Out Tests
# ============================================================================


class TestPoolFanOut:
    """Tests for parallel execution via pool.submit_fan_out_and_wait."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry with task queue methods."""
        from unittest.mock import AsyncMock

        registry = MagicMock(spec=AgentRegistry)

        # Mock async methods
        registry.submit_async = AsyncMock()
        registry.wait_for_task = AsyncMock()
        registry.wait_for_task_available = AsyncMock(return_value=True)
        registry.wait_for_queue_change = AsyncMock()
        registry.peek_next_task = AsyncMock(return_value=None)
        registry.mark_task_completed = AsyncMock()
        registry.all_agents.return_value = []

        # Mock task queue
        mock_queue = MagicMock()
        mock_queue._lock = asyncio.Lock()
        mock_queue._pending = {}
        mock_queue._completed = {}
        registry.task_queue = mock_queue

        return registry

    @pytest.mark.asyncio
    async def test_submit_fan_out_requires_two_intents(self, mock_registry):
        """Test that fan-out requires at least 2 intents."""
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        pool = SelfSelectingPool(mock_registry)

        result = await pool.submit_fan_out_and_wait(
            intents=["only one"],
            join_intent="combine",
        )

        assert not result.success
        assert "at least 2 intents" in result.error

    @pytest.mark.asyncio
    async def test_submit_fan_out_posts_parallel_tasks(self, mock_registry):
        """Test that fan-out posts multiple tasks to the queue."""
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        pool = SelfSelectingPool(mock_registry)

        # Mock intent router to avoid LLM calls
        pool._intent_router.find_agent_for_intent = AsyncMock(return_value=None)

        # Mock wait_for_task to return completed tasks
        completed_tasks = {}

        async def mock_wait(task_id, timeout=None):
            # Create a completed task for each parallel task
            from youtube_autonomous_agents.models import Task, TaskResult, TaskStatus

            task = Task(id=task_id, description="test", required_capabilities=[])
            task.status = TaskStatus.COMPLETED
            task.result = TaskResult(success=True, data={"task_id": task_id})
            completed_tasks[task_id] = task
            return task

        mock_registry.wait_for_task = AsyncMock(side_effect=mock_wait)

        # Mock finding join task
        with patch.object(pool, "_find_join_task") as mock_find_join:
            # Create a mock join task
            from youtube_autonomous_agents.models import Task, TaskResult, TaskStatus

            join_task = Task(id="join-123", description="combine", required_capabilities=[])
            join_task.status = TaskStatus.COMPLETED
            join_task.result = TaskResult(success=True, data={"joined": True})
            mock_find_join.return_value = join_task

            result = await pool.submit_fan_out_and_wait(
                intents=["search A", "search B"],
                join_intent="combine results",
                timeout=5.0,
            )

        # Verify 2 parallel tasks were submitted
        assert mock_registry.submit_async.call_count == 2

    @pytest.mark.asyncio
    async def test_task_group_tracking(self):
        """Test that TaskGroup correctly tracks completion."""
        from youtube_autonomous_agents.infra.pool import TaskGroup

        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        # Initially not complete
        assert not group.is_complete
        assert group.collected_results == []

        # Add one result
        group.results["task-1"] = {"data": "result 1"}
        assert not group.is_complete

        # Add second result
        group.results["task-2"] = {"data": "result 2"}
        assert group.is_complete
        assert len(group.collected_results) == 2

    @pytest.mark.asyncio
    async def test_task_group_handles_errors(self):
        """Test that TaskGroup tracks errors alongside results."""
        from youtube_autonomous_agents.infra.pool import TaskGroup

        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2", "task-3"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        # One success, one error
        group.results["task-1"] = {"data": "result 1"}
        group.errors.append("task-2: Failed")
        assert not group.is_complete

        # Add third result
        group.results["task-3"] = {"data": "result 3"}
        assert group.is_complete
        assert len(group.collected_results) == 2
        assert len(group.errors) == 1


# ============================================================================
# Integration Tests
# ============================================================================


class TestParallelIntegration:
    """Integration tests for full parallel request flow."""

    @pytest.fixture
    def mock_registry(self):
        """Create a registry with mock agents."""
        from unittest.mock import AsyncMock

        registry = MagicMock(spec=AgentRegistry)

        search_agent = MagicMock()
        search_agent.name = "search"
        search_agent.description = "Searches YouTube"
        search_agent.capabilities = ["youtube_search"]

        registry.all_agents.return_value = [search_agent]

        # Mock async methods needed by pool
        registry.submit_async = AsyncMock()
        registry.wait_for_task = AsyncMock()
        registry.wait_for_task_available = AsyncMock(return_value=False)
        registry.mark_task_completed = AsyncMock()

        # Mock task queue
        mock_queue = MagicMock()
        mock_queue._lock = asyncio.Lock()
        mock_queue._pending = {}
        mock_queue._completed = {}
        registry.task_queue = mock_queue

        return registry

    @pytest.mark.asyncio
    async def test_synthesizer_uses_pool_for_parallel(self, mock_registry):
        """Test that Synthesizer delegates parallel execution to pool."""
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool
        from youtube_autonomous_agents.models.task import TaskResult

        mock_client = MagicMock()
        synthesizer = SynthesizerAgent(registry=mock_registry, client=mock_client)

        # Mock analyze to return parallel
        with patch.object(synthesizer, "_analyze_request") as mock_analyze:
            mock_analyze.return_value = RequestAnalysis.parallel(
                intents=["search A", "search B"],
                join_intent="combine",
            )

            # Mock pool's submit_fan_out_and_wait
            with patch.object(
                SelfSelectingPool, "submit_fan_out_and_wait"
            ) as mock_fan_out:
                mock_fan_out.return_value = TaskResult(
                    success=True,
                    data={"combined_results": ["result A", "result B"]},
                )

                # Mock pool start/shutdown
                with patch.object(SelfSelectingPool, "start"):
                    with patch.object(SelfSelectingPool, "shutdown"):
                        # Mock response synthesis
                        with patch.object(
                            synthesizer, "_synthesize_response"
                        ) as mock_synth:
                            mock_synth.return_value = "Here are your combined results..."

                            response = await synthesizer.process_request(
                                "Search channel A and channel B for recipes"
                            )

        # Verify flow - Synthesizer should delegate to pool
        mock_analyze.assert_called_once()
        mock_fan_out.assert_called_once()
        call_kwargs = mock_fan_out.call_args[1]
        assert "search A" in call_kwargs["intents"]
        assert "search B" in call_kwargs["intents"]
        assert response == "Here are your combined results..."

    @pytest.mark.asyncio
    async def test_synthesizer_uses_pool_for_sequential(self, mock_registry):
        """Test that Synthesizer delegates sequential execution to pool."""
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool
        from youtube_autonomous_agents.models.task import TaskResult

        mock_client = MagicMock()
        synthesizer = SynthesizerAgent(registry=mock_registry, client=mock_client)

        # Mock analyze to return sequential
        with patch.object(synthesizer, "_analyze_request") as mock_analyze:
            mock_analyze.return_value = RequestAnalysis.sequential(
                intent="search for videos"
            )

            # Mock pool's submit_and_wait
            with patch.object(SelfSelectingPool, "submit_and_wait") as mock_submit:
                mock_submit.return_value = TaskResult(
                    success=True,
                    data={"videos": ["video1", "video2"]},
                )

                # Mock pool start/shutdown
                with patch.object(SelfSelectingPool, "start"):
                    with patch.object(SelfSelectingPool, "shutdown"):
                        # Mock response synthesis
                        with patch.object(
                            synthesizer, "_synthesize_response"
                        ) as mock_synth:
                            mock_synth.return_value = "Found 2 videos..."

                            response = await synthesizer.process_request(
                                "Find videos about cooking"
                            )

        # Verify flow - Synthesizer should use submit_and_wait for sequential
        mock_analyze.assert_called_once()
        mock_submit.assert_called_once()
        assert response == "Found 2 videos..."
