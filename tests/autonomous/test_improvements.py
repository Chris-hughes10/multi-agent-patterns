"""Tests for V2 improvements: timeouts, event-driven joins, pool reuse.

Tests the three improvements:
1. OperationTimeout for context-aware timeout handling
2. Event-driven join task discovery (TaskGroup)
3. Pool reuse in SynthesizerAgent
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from youtube_autonomous_agents.infra.pool import TaskGroup
from youtube_autonomous_agents.models.handoff import OperationTimeout

# ============================================================================
# OperationTimeout Tests
# ============================================================================


class TestOperationTimeout:
    """Tests for the OperationTimeout model."""

    def test_create_operation_timeout(self):
        """Test creating an OperationTimeout with all fields."""
        timeout = OperationTimeout(
            operation="goal_reasoning",
            timeout_seconds=30.0,
            context={"goal": "find videos"},
            suggested_fallback="Use keyword matching instead",
            retryable=True,
        )
        assert timeout.operation == "goal_reasoning"
        assert timeout.timeout_seconds == 30.0
        assert timeout.context == {"goal": "find videos"}
        assert timeout.suggested_fallback == "Use keyword matching instead"
        assert timeout.retryable is True

    def test_operation_timeout_defaults(self):
        """Test OperationTimeout with default values."""
        timeout = OperationTimeout(
            operation="llm_call",
            timeout_seconds=10.0,
        )
        assert timeout.context == {}
        assert timeout.suggested_fallback is None
        assert timeout.retryable is True

    def test_to_dict(self):
        """Test converting OperationTimeout to dictionary."""
        timeout = OperationTimeout(
            operation="search",
            timeout_seconds=15.0,
            context={"query": "test"},
            suggested_fallback="Skip search",
            retryable=False,
        )
        result = timeout.to_dict()
        assert result == {
            "operation": "search",
            "timeout_seconds": 15.0,
            "context": {"query": "test"},
            "suggested_fallback": "Skip search",
            "retryable": False,
        }

    def test_from_dict(self):
        """Test creating OperationTimeout from dictionary."""
        data = {
            "operation": "summarize",
            "timeout_seconds": 20.0,
            "context": {"text": "long text"},
            "suggested_fallback": "Return partial",
            "retryable": True,
        }
        timeout = OperationTimeout.from_dict(data)
        assert timeout.operation == "summarize"
        assert timeout.timeout_seconds == 20.0
        assert timeout.context == {"text": "long text"}
        assert timeout.suggested_fallback == "Return partial"
        assert timeout.retryable is True

    def test_from_dict_with_defaults(self):
        """Test from_dict with missing optional fields."""
        data = {"operation": "test"}
        timeout = OperationTimeout.from_dict(data)
        assert timeout.operation == "test"
        assert timeout.timeout_seconds == 0.0
        assert timeout.context == {}
        assert timeout.suggested_fallback is None
        assert timeout.retryable is True

    def test_str_representation(self):
        """Test string representation of OperationTimeout."""
        timeout = OperationTimeout(
            operation="llm_call",
            timeout_seconds=30.0,
        )
        assert "llm_call" in str(timeout)
        assert "30.0s" in str(timeout)

    def test_str_with_suggestion(self):
        """Test string representation includes suggestion when present."""
        timeout = OperationTimeout(
            operation="llm_call",
            timeout_seconds=30.0,
            suggested_fallback="Try again",
        )
        assert "Try again" in str(timeout)


# ============================================================================
# BaseAgent Timeout Helper Tests
# ============================================================================


class TestBaseAgentTimeout:
    """Tests for BaseAgent timeout helper methods."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent for testing timeout helpers."""
        from youtube_autonomous_agents.agents.base import BaseAgent

        class TestAgent(BaseAgent):
            @property
            def name(self) -> str:
                return "test"

            @property
            def capabilities(self) -> list[str]:
                return ["test_capability"]

            def _get_instructions(self) -> str:
                return "Test agent"

            def _get_tools(self) -> list:
                return []

        registry = MagicMock()
        return TestAgent(registry=registry, llm_timeout=1.0)

    @pytest.mark.asyncio
    async def test_call_with_timeout_success(self, mock_agent):
        """Test _call_with_timeout returns result on success."""

        async def quick_operation():
            return "success"

        result = await mock_agent._call_with_timeout(
            quick_operation(),
            operation="test_op",
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_call_with_timeout_returns_timeout_object(self, mock_agent):
        """Test _call_with_timeout returns OperationTimeout on timeout."""

        async def slow_operation():
            await asyncio.sleep(10)
            return "never reached"

        result = await mock_agent._call_with_timeout(
            slow_operation(),
            operation="slow_op",
            timeout=0.01,  # Very short timeout
            context={"input": "test"},
            suggested_fallback="Use cache",
        )

        assert isinstance(result, OperationTimeout)
        assert result.operation == "slow_op"
        assert result.timeout_seconds == 0.01
        assert result.context == {"input": "test"}
        assert result.suggested_fallback == "Use cache"

    @pytest.mark.asyncio
    async def test_call_with_timeout_uses_default_timeout(self, mock_agent):
        """Test _call_with_timeout uses agent's default timeout."""

        async def slow_operation():
            await asyncio.sleep(10)
            return "never reached"

        # Agent has 1.0s timeout, operation takes 10s
        result = await mock_agent._call_with_timeout(
            slow_operation(),
            operation="test_op",
        )

        assert isinstance(result, OperationTimeout)
        assert result.timeout_seconds == 1.0  # Default from agent

    @pytest.mark.asyncio
    async def test_call_with_timeout_or_raise_success(self, mock_agent):
        """Test _call_with_timeout_or_raise returns result on success."""

        async def quick_operation():
            return "success"

        result = await mock_agent._call_with_timeout_or_raise(
            quick_operation(),
            operation="test_op",
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_call_with_timeout_or_raise_raises(self, mock_agent):
        """Test _call_with_timeout_or_raise raises TimeoutError."""

        async def slow_operation():
            await asyncio.sleep(10)
            return "never reached"

        with pytest.raises(TimeoutError) as exc_info:
            await mock_agent._call_with_timeout_or_raise(
                slow_operation(),
                operation="slow_op",
                timeout=0.01,
            )

        assert "slow_op" in str(exc_info.value)
        assert "0.01s" in str(exc_info.value)


# ============================================================================
# TaskGroup Event-Driven Join Tests
# ============================================================================


class TestTaskGroupEventDriven:
    """Tests for event-driven TaskGroup join notification."""

    def test_task_group_has_event(self):
        """Test TaskGroup initializes with event."""
        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )
        assert group._join_posted is not None
        assert not group._join_posted.is_set()
        assert group.join_task_id is None

    def test_signal_join_posted(self):
        """Test signaling that join task was posted."""
        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        group.signal_join_posted("join-task-123")

        assert group._join_posted.is_set()
        assert group.join_task_id == "join-task-123"

    @pytest.mark.asyncio
    async def test_wait_for_join_immediate(self):
        """Test wait_for_join returns immediately when already signaled."""
        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        # Signal before waiting
        group.signal_join_posted("join-task-456")

        # Should return immediately
        result = await group.wait_for_join(timeout=1.0)
        assert result == "join-task-456"

    @pytest.mark.asyncio
    async def test_wait_for_join_with_delay(self):
        """Test wait_for_join waits for signal."""
        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        async def signal_later():
            await asyncio.sleep(0.1)
            group.signal_join_posted("delayed-join-task")

        # Start signaling in background
        asyncio.create_task(signal_later())

        # Wait for signal
        result = await group.wait_for_join(timeout=1.0)
        assert result == "delayed-join-task"

    @pytest.mark.asyncio
    async def test_wait_for_join_timeout(self):
        """Test wait_for_join returns None on timeout."""
        group = TaskGroup(
            id="test-group",
            task_ids=["task-1", "task-2"],
            join_intent="combine",
            state={},
            parent_task_id="parent-1",
        )

        # Don't signal, should timeout
        result = await group.wait_for_join(timeout=0.05)
        assert result is None


# ============================================================================
# SynthesizerAgent Pool Reuse Tests
# ============================================================================


class TestSynthesizerPoolReuse:
    """Tests for SynthesizerAgent pool reuse functionality."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry."""
        from youtube_autonomous_agents.infra import AgentRegistry

        registry = MagicMock(spec=AgentRegistry)
        registry.all_agents.return_value = []
        return registry

    @pytest.fixture
    def mock_client(self):
        """Create a mock chat client."""
        client = MagicMock()
        return client

    def test_synthesizer_accepts_external_pool(self, mock_registry, mock_client):
        """Test SynthesizerAgent can be initialized with external pool."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        external_pool = SelfSelectingPool(mock_registry)

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
            pool=external_pool,
        )

        assert synth._external_pool is external_pool

    def test_synthesizer_default_no_pool(self, mock_registry, mock_client):
        """Test SynthesizerAgent defaults to no external pool (CLI mode)."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
        )

        assert synth._external_pool is None

    @pytest.mark.asyncio
    async def test_get_pool_creates_new_in_cli_mode(self, mock_registry, mock_client):
        """Test _get_pool creates new pool in CLI mode."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
        )

        pool, should_shutdown = await synth._get_pool()

        assert isinstance(pool, SelfSelectingPool)
        assert should_shutdown is True  # CLI mode should shutdown

        # Clean up
        await pool.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_get_pool_returns_external_pool(self, mock_registry, mock_client):
        """Test _get_pool returns external pool in service mode."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        external_pool = SelfSelectingPool(mock_registry)
        await external_pool.start()

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
            pool=external_pool,
        )

        pool, should_shutdown = await synth._get_pool()

        assert pool is external_pool  # Same instance
        assert should_shutdown is False  # Service mode should NOT shutdown

        # Clean up
        await external_pool.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_get_pool_starts_stopped_external_pool(
        self, mock_registry, mock_client
    ):
        """Test _get_pool starts external pool if not running."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        external_pool = SelfSelectingPool(mock_registry)
        # Don't start it

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
            pool=external_pool,
        )

        pool, should_shutdown = await synth._get_pool()

        assert pool is external_pool
        assert pool.is_running is True  # Should have been started
        assert should_shutdown is False

        # Clean up
        await external_pool.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_process_request_shutdowns_cli_pool(
        self, mock_registry, mock_client
    ):
        """Test process_request shuts down pool in CLI mode."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
        )

        # Mock analyze to return sequential
        with patch.object(synth, "_analyze_request") as mock_analyze:
            from youtube_autonomous_agents.agents.synthesizer import RequestAnalysis

            mock_analyze.return_value = RequestAnalysis.sequential("test")

            # Mock pool methods
            with patch.object(SelfSelectingPool, "submit_and_wait") as mock_submit:
                from youtube_autonomous_agents.models.task import TaskResult

                mock_submit.return_value = TaskResult(success=True, data={"test": True})

                with patch.object(SelfSelectingPool, "start"), patch.object(
                    SelfSelectingPool, "shutdown"
                ) as mock_shutdown, patch.object(synth, "_synthesize_response") as mock_synth:
                    mock_synth.return_value = "Response"

                    await synth.process_request("test request")

                    # Shutdown should be called in CLI mode
                    mock_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_request_does_not_shutdown_external_pool(
        self, mock_registry, mock_client
    ):
        """Test process_request does NOT shut down external pool."""
        from youtube_autonomous_agents.agents.synthesizer import SynthesizerAgent
        from youtube_autonomous_agents.infra.pool import SelfSelectingPool

        external_pool = SelfSelectingPool(mock_registry)

        synth = SynthesizerAgent(
            registry=mock_registry,
            client=mock_client,
            pool=external_pool,
        )

        # Mock analyze to return sequential
        with patch.object(synth, "_analyze_request") as mock_analyze:
            from youtube_autonomous_agents.agents.synthesizer import RequestAnalysis

            mock_analyze.return_value = RequestAnalysis.sequential("test")

            # Mock pool methods
            with patch.object(external_pool, "submit_and_wait") as mock_submit:
                from youtube_autonomous_agents.models.task import TaskResult

                mock_submit.return_value = TaskResult(success=True, data={"test": True})

                with patch.object(external_pool, "start"), patch.object(
                    external_pool, "shutdown"
                ) as mock_shutdown, patch.object(synth, "_synthesize_response") as mock_synth:
                    mock_synth.return_value = "Response"

                    await synth.process_request("test request")

                    # Shutdown should NOT be called for external pool
                    mock_shutdown.assert_not_called()
