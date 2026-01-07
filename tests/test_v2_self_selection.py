"""Tests for V2 Self-Selection pattern."""

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from youtube_agent_v2.core import AgentRegistry, BaseAgent, Task, TaskResult
from youtube_agent_v2.patterns.self_selection import SelfSelectingPool, run_with_self_selection


class MockAgent(BaseAgent):
    """Test agent with configurable behavior."""

    def __init__(
        self,
        registry: AgentRegistry,
        name: str = "mock",
        capabilities: list[str] | None = None,
        delay: float = 0.0,
        should_fail: bool = False,
    ):
        # Don't call super().__init__ to avoid needing real client
        self._registry = registry
        self._name = name
        self._capabilities = capabilities or ["test_capability"]
        self._delay = delay
        self._should_fail = should_fail
        self._executed_tasks: list[Task] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> list[str]:
        return self._capabilities

    def _get_instructions(self) -> str:
        return "Test agent"

    def _get_tools(self) -> list[Callable[..., Any]]:
        return []

    async def execute(self, task: Task) -> TaskResult:
        """Execute with optional delay and failure."""
        self._executed_tasks.append(task)

        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._should_fail:
            return TaskResult(success=False, error="Mock failure")

        return TaskResult(success=True, data=f"Executed by {self._name}: {task.description}")


class TestSelfSelectingPool:
    """Tests for SelfSelectingPool."""

    @pytest.fixture
    def registry(self) -> AgentRegistry:
        """Create an empty registry."""
        return AgentRegistry()

    async def test_agent_claims_and_executes_task(self, registry: AgentRegistry) -> None:
        """Test that an agent can claim and execute a task."""
        agent = MockAgent(registry, name="test", capabilities=["search"])
        registry.register(agent)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            result = await pool.submit_and_wait(
                description="Test task",
                capabilities=["search"],
                timeout=5.0,
            )

            assert result.success is True
            assert "Executed by test" in result.data
            assert len(agent._executed_tasks) == 1
        finally:
            await pool.shutdown()

    async def test_correct_agent_claims_task(self, registry: AgentRegistry) -> None:
        """Test that only agents with matching capabilities claim tasks."""
        search_agent = MockAgent(registry, name="search", capabilities=["youtube_search"])
        summary_agent = MockAgent(registry, name="summary", capabilities=["summarization"])
        registry.register(search_agent)
        registry.register(summary_agent)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            # Submit search task - should be claimed by search agent
            result = await pool.submit_and_wait(
                description="Search task",
                capabilities=["youtube_search"],
                timeout=5.0,
            )

            assert result.success is True
            assert "Executed by search" in result.data
            assert len(search_agent._executed_tasks) == 1
            assert len(summary_agent._executed_tasks) == 0

        finally:
            await pool.shutdown()

    async def test_multiple_agents_compete_for_tasks(self, registry: AgentRegistry) -> None:
        """Test that multiple capable agents compete for tasks."""
        # Create two agents with the same capability
        agent1 = MockAgent(registry, name="agent1", capabilities=["test"])
        agent2 = MockAgent(registry, name="agent2", capabilities=["test"])
        registry.register(agent1)
        registry.register(agent2)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            # Submit a task - one of the agents should claim it
            result = await pool.submit_and_wait(
                description="Shared capability task",
                capabilities=["test"],
                timeout=5.0,
            )

            assert result.success is True
            # One agent should have executed, the other should not
            total_executed = len(agent1._executed_tasks) + len(agent2._executed_tasks)
            assert total_executed == 1

        finally:
            await pool.shutdown()

    async def test_no_capable_agent_times_out(self, registry: AgentRegistry) -> None:
        """Test that tasks time out when no agent can handle them."""
        agent = MockAgent(registry, name="writer", capabilities=["file_export"])
        registry.register(agent)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            result = await pool.submit_and_wait(
                description="Search task",
                capabilities=["youtube_search"],  # No agent has this
                timeout=0.5,  # Short timeout
            )

            assert result.success is False
            assert "timed out" in result.error.lower()

        finally:
            await pool.shutdown()

    async def test_agent_failure_returns_error_result(self, registry: AgentRegistry) -> None:
        """Test that agent failures are captured in TaskResult."""
        agent = MockAgent(registry, name="failing", capabilities=["test"], should_fail=True)
        registry.register(agent)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            result = await pool.submit_and_wait(
                description="Will fail",
                capabilities=["test"],
                timeout=5.0,
            )

            assert result.success is False
            assert "Mock failure" in result.error

        finally:
            await pool.shutdown()

    async def test_multiple_tasks_distributed(self, registry: AgentRegistry) -> None:
        """Test that multiple tasks are distributed among agents."""
        # Create agents with small delays to ensure tasks get distributed
        agent1 = MockAgent(registry, name="agent1", capabilities=["test"], delay=0.05)
        agent2 = MockAgent(registry, name="agent2", capabilities=["test"], delay=0.05)
        registry.register(agent1)
        registry.register(agent2)

        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            # Submit multiple tasks concurrently
            tasks = [
                pool.submit_and_wait(
                    description=f"Task {i}",
                    capabilities=["test"],
                    timeout=5.0,
                )
                for i in range(4)
            ]

            results = await asyncio.gather(*tasks)

            # All should succeed
            assert all(r.success for r in results)

            # Tasks should be distributed (both agents should have work)
            total = len(agent1._executed_tasks) + len(agent2._executed_tasks)
            assert total == 4

        finally:
            await pool.shutdown()

    async def test_pool_shutdown_stops_watchers(self, registry: AgentRegistry) -> None:
        """Test that shutdown stops all agent watchers."""
        agent = MockAgent(registry, name="test", capabilities=["test"])
        registry.register(agent)

        pool = SelfSelectingPool(registry)
        await pool.start()

        assert pool.active_watcher_count == 1
        assert pool.is_running is True

        await pool.shutdown()

        assert pool.is_running is False


class TestRunWithSelfSelection:
    """Tests for run_with_self_selection convenience function."""

    async def test_run_with_self_selection_executes_task(self) -> None:
        """Test the convenience function runs a single task end-to-end."""
        registry = AgentRegistry()
        agent = MockAgent(registry, name="test", capabilities=["search"])
        registry.register(agent)

        result = await run_with_self_selection(
            registry=registry,
            description="Single task",
            capabilities=["search"],
            timeout=5.0,
        )

        assert result.success is True
        assert "Executed by test" in result.data


class TestSelfSelectionWithRealAgents:
    """Integration tests with real V2 agent classes (mocked tools)."""

    async def test_registry_with_all_v2_agents_self_selection(self) -> None:
        """Test that all V2 agents work with self-selection pattern."""
        from youtube_agent_v2.agents import (
            SearchAgent,
            SummarizeAgent,
            TranscriptAgent,
            WriterAgent,
        )

        registry = AgentRegistry()

        # Mock the chat client to avoid Azure calls
        mock_client = MagicMock()

        # Create agents with mocked client
        search = SearchAgent(registry, client=mock_client)
        transcript = TranscriptAgent(registry, client=mock_client)
        summarize = SummarizeAgent(registry, client=mock_client)
        writer = WriterAgent(registry, client=mock_client)

        registry.register(search)
        registry.register(transcript)
        registry.register(summarize)
        registry.register(writer)

        # Create pool and verify agents are watching
        pool = SelfSelectingPool(registry)
        await pool.start()

        try:
            assert pool.active_watcher_count == 4
            assert pool.is_running is True
        finally:
            await pool.shutdown()


class TestDispatcherVsSelfSelection:
    """Comparison tests between dispatcher and self-selection patterns."""

    async def test_both_patterns_produce_same_result(self) -> None:
        """Test that both patterns successfully execute the same task."""
        from youtube_agent_v2.patterns.dispatcher import run_with_dispatcher

        # Create identical registries for fair comparison
        def create_test_registry() -> tuple[AgentRegistry, MockAgent]:
            registry = AgentRegistry()
            agent = MockAgent(registry, name="test", capabilities=["search"])
            registry.register(agent)
            return registry, agent

        # Test dispatcher
        registry1, agent1 = create_test_registry()
        result1 = await run_with_dispatcher(
            registry=registry1,
            description="Test task",
            capabilities=["search"],
            timeout=5.0,
        )

        # Test self-selection
        registry2, agent2 = create_test_registry()
        result2 = await run_with_self_selection(
            registry=registry2,
            description="Test task",
            capabilities=["search"],
            timeout=5.0,
        )

        # Both should succeed with similar results
        assert result1.success is True
        assert result2.success is True
        assert "Executed by test" in result1.data
        assert "Executed by test" in result2.data
