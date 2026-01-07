"""Tests for V2 Dispatcher pattern."""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from youtube_agent_v2.core import AgentRegistry, BaseAgent, Task, TaskResult
from youtube_agent_v2.patterns.dispatcher import DispatcherCoordinator, run_with_dispatcher


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


class TestDispatcherCoordinator:
    """Tests for DispatcherCoordinator."""

    @pytest.fixture
    def registry(self) -> AgentRegistry:
        """Create an empty registry."""
        return AgentRegistry()

    @pytest.fixture
    def dispatcher(self, registry: AgentRegistry) -> DispatcherCoordinator:
        """Create a dispatcher with the registry."""
        return DispatcherCoordinator(registry)

    async def test_submit_and_wait_returns_result(
        self, registry: AgentRegistry, dispatcher: DispatcherCoordinator
    ) -> None:
        """Test that submit_and_wait returns a result from the agent."""
        agent = MockAgent(registry, name="test", capabilities=["search"])
        registry.register(agent)

        # Start dispatcher in background
        dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=1))

        try:
            result = await dispatcher.submit_and_wait(
                description="Test task",
                capabilities=["search"],
                timeout=5.0,
            )

            assert result.success is True
            assert "Executed by test" in result.data
            assert len(agent._executed_tasks) == 1
        finally:
            await dispatcher.shutdown()
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task

    async def test_dispatcher_routes_to_correct_agent(self, registry: AgentRegistry) -> None:
        """Test that tasks are routed to agents with matching capabilities."""
        search_agent = MockAgent(registry, name="search", capabilities=["youtube_search"])
        summary_agent = MockAgent(registry, name="summary", capabilities=["summarization"])
        registry.register(search_agent)
        registry.register(summary_agent)

        dispatcher = DispatcherCoordinator(registry)
        dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=2))

        try:
            # Submit search task
            result1 = await dispatcher.submit_and_wait(
                description="Search task",
                capabilities=["youtube_search"],
                timeout=5.0,
            )

            # Submit summary task
            result2 = await dispatcher.submit_and_wait(
                description="Summary task",
                capabilities=["summarization"],
                timeout=5.0,
            )

            assert result1.success is True
            assert "Executed by search" in result1.data
            assert len(search_agent._executed_tasks) == 1

            assert result2.success is True
            assert "Executed by summary" in result2.data
            assert len(summary_agent._executed_tasks) == 1

        finally:
            await dispatcher.shutdown()
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task

    async def test_no_capable_agent_returns_failure(
        self, registry: AgentRegistry, dispatcher: DispatcherCoordinator
    ) -> None:
        """Test that tasks fail gracefully when no agent can handle them."""
        agent = MockAgent(registry, name="writer", capabilities=["file_export"])
        registry.register(agent)

        dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=1))

        try:
            result = await dispatcher.submit_and_wait(
                description="Search task",
                capabilities=["youtube_search"],  # No agent has this
                timeout=5.0,
            )

            assert result.success is False
            assert "No agent found" in result.error

        finally:
            await dispatcher.shutdown()
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task

    async def test_concurrent_execution_respects_limit(self, registry: AgentRegistry) -> None:
        """Test that max_concurrent limits parallel execution."""
        # Create agent with delay to allow overlap detection
        agent = MockAgent(registry, name="slow", capabilities=["test"], delay=0.1)
        registry.register(agent)

        dispatcher = DispatcherCoordinator(registry)
        dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=2))

        try:
            # Submit 3 tasks concurrently
            tasks = [
                dispatcher.submit_and_wait(
                    description=f"Task {i}",
                    capabilities=["test"],
                    timeout=5.0,
                )
                for i in range(3)
            ]

            results = await asyncio.gather(*tasks)

            # All should succeed
            assert all(r.success for r in results)
            assert len(agent._executed_tasks) == 3

        finally:
            await dispatcher.shutdown()
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task

    async def test_agent_failure_returns_error_result(self, registry: AgentRegistry) -> None:
        """Test that agent failures are captured in TaskResult."""
        agent = MockAgent(registry, name="failing", capabilities=["test"], should_fail=True)
        registry.register(agent)

        dispatcher = DispatcherCoordinator(registry)
        dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=1))

        try:
            result = await dispatcher.submit_and_wait(
                description="Will fail",
                capabilities=["test"],
                timeout=5.0,
            )

            assert result.success is False
            assert "Mock failure" in result.error

        finally:
            await dispatcher.shutdown()
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task


class TestRunWithDispatcher:
    """Tests for run_with_dispatcher convenience function."""

    async def test_run_with_dispatcher_executes_single_task(self) -> None:
        """Test the convenience function runs a single task end-to-end."""
        registry = AgentRegistry()
        agent = MockAgent(registry, name="test", capabilities=["search"])
        registry.register(agent)

        result = await run_with_dispatcher(
            registry=registry,
            description="Single task",
            capabilities=["search"],
            timeout=5.0,
        )

        assert result.success is True
        assert "Executed by test" in result.data


class TestDispatcherWithRealAgents:
    """Integration tests with real V2 agent classes (mocked tools)."""

    async def test_registry_with_all_v2_agents(self) -> None:
        """Test that all V2 agents can be registered and discovered."""
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

        assert len(registry) == 4

        # Test capability discovery
        search_task = Task(description="search", required_capabilities=["youtube_search"])
        assert registry.find_agents_for_task(search_task)[0].name == "search"

        summary_task = Task(description="summarize", required_capabilities=["summarization"])
        assert registry.find_agents_for_task(summary_task)[0].name == "summarize"

        transcript_task = Task(description="fetch", required_capabilities=["transcript_fetch"])
        assert registry.find_agents_for_task(transcript_task)[0].name == "transcript"

        writer_task = Task(description="write", required_capabilities=["file_export"])
        assert registry.find_agents_for_task(writer_task)[0].name == "writer"
