"""Tests for the Planner + DAG execution pattern.

Tests cover:
- ExecutionDAG data structure and validation
- DAGStep status management
- DAGExecutor parallel execution with dependencies
- Variable resolution from session
- PlannerAgent plan creation (with mocked LLM)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from youtube_agent_planner.infra.dag_executor import (
    DAGExecutor,
    DAGStep,
    ExecutionDAG,
    StepStatus,
)
from youtube_goal_agents.infra.registry import AgentRegistry
from youtube_goal_agents.infra.session import Session
from youtube_goal_agents.models import TaskResult
from youtube_goal_agents.models.handoff import PartialResult

# ============================================================================
# ExecutionDAG Tests
# ============================================================================


class TestDAGStep:
    """Tests for DAGStep data structure."""

    def test_create_step_with_defaults(self) -> None:
        """Test creating a DAGStep with minimal args."""
        step = DAGStep(
            id="search",
            agent_name="search",
            description="Search for videos",
            input_template={"query": "test"},
        )

        assert step.id == "search"
        assert step.agent_name == "search"
        assert step.status == StepStatus.PENDING
        assert step.depends_on == []

    def test_create_step_with_dependencies(self) -> None:
        """Test creating a step with dependencies."""
        step = DAGStep(
            id="summarize",
            agent_name="summarize",
            description="Summarize transcript",
            input_template={"text": "$transcript"},
            depends_on=["search", "transcript"],
        )

        assert step.depends_on == ["search", "transcript"]

    def test_step_status_transitions(self) -> None:
        """Test updating step status."""
        step = DAGStep(
            id="test",
            agent_name="test",
            description="Test step",
            input_template={},
        )

        assert step.status == StepStatus.PENDING

        step.status = StepStatus.READY
        assert step.status == StepStatus.READY

        step.status = StepStatus.RUNNING
        assert step.status == StepStatus.RUNNING

        step.status = StepStatus.COMPLETED
        assert step.status == StepStatus.COMPLETED


class TestExecutionDAG:
    """Tests for ExecutionDAG data structure."""

    def test_create_empty_dag(self) -> None:
        """Test creating an empty DAG."""
        dag = ExecutionDAG(goal="Test goal", steps=[])

        assert dag.goal == "Test goal"
        assert len(dag.steps) == 0

    def test_create_dag_with_steps(self) -> None:
        """Test creating a DAG with multiple steps."""
        steps = [
            DAGStep(
                id="search",
                agent_name="search",
                description="Search",
                input_template={"query": "test"},
            ),
            DAGStep(
                id="transcript",
                agent_name="transcript",
                description="Get transcript",
                input_template={"video_id": "$search.video_id"},
                depends_on=["search"],
            ),
        ]
        dag = ExecutionDAG(goal="Find and transcribe", steps=steps)

        assert len(dag.steps) == 2
        assert dag.get_step("search") is not None
        assert dag.get_step("transcript") is not None

    def test_get_ready_steps_initial(self) -> None:
        """Test getting ready steps when no dependencies are satisfied."""
        steps = [
            DAGStep(
                id="a",
                agent_name="agent",
                description="Step A",
                input_template={},
            ),
            DAGStep(
                id="b",
                agent_name="agent",
                description="Step B",
                input_template={},
                depends_on=["a"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        ready = dag.get_ready_steps(completed_steps=set())

        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_get_ready_steps_after_completion(self) -> None:
        """Test getting ready steps after some complete."""
        steps = [
            DAGStep(
                id="a",
                agent_name="agent",
                description="Step A",
                input_template={},
            ),
            DAGStep(
                id="b",
                agent_name="agent",
                description="Step B",
                input_template={},
                depends_on=["a"],
            ),
            DAGStep(
                id="c",
                agent_name="agent",
                description="Step C",
                input_template={},
                depends_on=["a"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        # Mark A as completed (as the executor would do)
        dag.get_step("a").status = StepStatus.COMPLETED

        # After A completes, both B and C should be ready
        ready = dag.get_ready_steps(completed_steps={"a"})

        assert len(ready) == 2
        ready_ids = {s.id for s in ready}
        assert ready_ids == {"b", "c"}

    def test_get_ready_steps_multiple_deps(self) -> None:
        """Test step with multiple dependencies."""
        steps = [
            DAGStep(id="a", agent_name="agent", description="A", input_template={}),
            DAGStep(id="b", agent_name="agent", description="B", input_template={}),
            DAGStep(
                id="c",
                agent_name="agent",
                description="C",
                input_template={},
                depends_on=["a", "b"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        # Initially, A and B are ready (no dependencies)
        ready_initial = dag.get_ready_steps(completed_steps=set())
        assert len(ready_initial) == 2

        # Mark A as completed - C still not ready (needs B too)
        dag.get_step("a").status = StepStatus.COMPLETED
        ready_after_a = dag.get_ready_steps(completed_steps={"a"})
        # Only B should be ready (A is completed, C still needs B)
        assert len(ready_after_a) == 1
        assert ready_after_a[0].id == "b"

        # Mark B as completed - C is now ready
        dag.get_step("b").status = StepStatus.COMPLETED
        ready_after_both = dag.get_ready_steps(completed_steps={"a", "b"})
        assert len(ready_after_both) == 1
        assert ready_after_both[0].id == "c"

    def test_validate_valid_dag(self) -> None:
        """Test validation passes for valid DAG."""
        steps = [
            DAGStep(id="a", agent_name="agent", description="A", input_template={}),
            DAGStep(
                id="b",
                agent_name="agent",
                description="B",
                input_template={},
                depends_on=["a"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        errors = dag.validate()

        assert len(errors) == 0

    def test_validate_missing_dependency(self) -> None:
        """Test validation catches missing dependencies."""
        steps = [
            DAGStep(
                id="b",
                agent_name="agent",
                description="B",
                input_template={},
                depends_on=["nonexistent"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        errors = dag.validate()

        assert len(errors) == 1
        assert "nonexistent" in errors[0]

    def test_validate_duplicate_ids(self) -> None:
        """Test validation catches duplicate step IDs."""
        steps = [
            DAGStep(id="a", agent_name="agent", description="A", input_template={}),
            DAGStep(id="a", agent_name="agent", description="A2", input_template={}),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        errors = dag.validate()

        assert len(errors) == 1
        assert "Duplicate" in errors[0]

    def test_validate_self_dependency(self) -> None:
        """Test validation catches self-dependencies."""
        steps = [
            DAGStep(
                id="a",
                agent_name="agent",
                description="A",
                input_template={},
                depends_on=["a"],
            ),
        ]
        dag = ExecutionDAG(goal="Test", steps=steps)

        errors = dag.validate()

        assert len(errors) == 1
        # The validation uses "Circular dependency" for self-references
        assert "Circular" in errors[0] or "itself" in errors[0]

    def test_from_dict(self) -> None:
        """Test creating DAG from dict (as returned by LLM)."""
        data = {
            "goal": "Search and summarize",
            "steps": [
                {
                    "id": "search",
                    "agent": "search",
                    "description": "Find videos",
                    "input": {"query": "test"},
                    "depends_on": [],
                },
                {
                    "id": "summarize",
                    "agent": "summarize",
                    "description": "Summarize",
                    "input": {"text": "$search.text"},
                    "depends_on": ["search"],
                },
            ],
        }

        dag = ExecutionDAG.from_dict(data)

        assert dag.goal == "Search and summarize"
        assert len(dag.steps) == 2
        assert dag.get_step("search").agent_name == "search"
        assert dag.get_step("summarize").depends_on == ["search"]


# ============================================================================
# DAGExecutor Tests
# ============================================================================


class TestDAGExecutor:
    """Tests for DAGExecutor."""

    @pytest.fixture
    def mock_registry(self) -> AgentRegistry:
        """Create a mock registry with test agents."""
        registry = AgentRegistry()

        # Create mock agents
        for name in ["search", "transcript", "summarize"]:
            agent = MagicMock()
            agent.name = name
            agent.capabilities = [name]
            agent.execute = AsyncMock(
                return_value=TaskResult(
                    success=True,
                    data={f"{name}_result": f"Result from {name}"},
                )
            )
            registry.register(agent)

        return registry

    @pytest.fixture
    def session(self) -> Session:
        """Create a fresh session."""
        return Session()

    def test_create_executor(self, mock_registry: AgentRegistry, session: Session) -> None:
        """Test creating a DAGExecutor."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        assert executor._registry is mock_registry
        assert executor._session is session

    @pytest.mark.asyncio
    async def test_execute_single_step(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test executing a DAG with a single step."""
        dag = ExecutionDAG(
            goal="Search",
            steps=[
                DAGStep(
                    id="search",
                    agent_name="search",
                    description="Search",
                    input_template={"query": "test"},
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        result = await executor.execute(dag)

        assert isinstance(result, dict)
        assert "search" in result

    @pytest.mark.asyncio
    async def test_execute_sequential_steps(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test executing steps in sequence (with dependencies)."""
        dag = ExecutionDAG(
            goal="Search then summarize",
            steps=[
                DAGStep(
                    id="search",
                    agent_name="search",
                    description="Search",
                    input_template={"query": "test"},
                ),
                DAGStep(
                    id="summarize",
                    agent_name="summarize",
                    description="Summarize",
                    input_template={"text": "some text"},
                    depends_on=["search"],
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        result = await executor.execute(dag)

        assert isinstance(result, dict)
        assert "search" in result
        assert "summarize" in result

    @pytest.mark.asyncio
    async def test_execute_parallel_steps(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test that independent steps can run in parallel."""
        # Track execution timing
        execution_times: dict[str, list[float]] = {}

        async def track_execution(name: str, _task: any) -> TaskResult:
            import time

            execution_times[name] = [time.time()]
            await asyncio.sleep(0.1)  # Simulate some work
            execution_times[name].append(time.time())
            return TaskResult(
                success=True,
                data={f"{name}_result": f"Result from {name}"},
            )

        # Set up tracked agents - create fresh mocks to avoid fixture interference
        search_agent = mock_registry.get_agent("search")
        transcript_agent = mock_registry.get_agent("transcript")

        # Use functools.partial to properly capture the name
        from functools import partial

        search_agent.execute = AsyncMock(side_effect=partial(track_execution, "search"))
        transcript_agent.execute = AsyncMock(side_effect=partial(track_execution, "transcript"))

        dag = ExecutionDAG(
            goal="Parallel execution",
            steps=[
                DAGStep(
                    id="search",
                    agent_name="search",
                    description="Search",
                    input_template={},
                ),
                DAGStep(
                    id="transcript",
                    agent_name="transcript",
                    description="Transcript",
                    input_template={},
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        await executor.execute(dag)

        # Both agents should have been called
        assert "search" in execution_times, "search agent was not called"
        assert "transcript" in execution_times, "transcript agent was not called"

        # If running in parallel, the start times should be very close
        # (both start before either finishes)
        search_start = execution_times["search"][0]
        transcript_start = execution_times["transcript"][0]

        # They should start within 0.05s of each other if parallel
        assert abs(search_start - transcript_start) < 0.05, (
            f"Agents did not start in parallel: "
            f"search={search_start}, transcript={transcript_start}"
        )

    @pytest.mark.asyncio
    async def test_execute_handles_agent_failure(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test handling when an agent fails."""
        # Make search agent fail
        search_agent = mock_registry.get_agent("search")
        search_agent.execute = AsyncMock(
            return_value=TaskResult(
                success=False,
                error="Search API unavailable",
            )
        )

        dag = ExecutionDAG(
            goal="Search",
            steps=[
                DAGStep(
                    id="search",
                    agent_name="search",
                    description="Search",
                    input_template={},
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        result = await executor.execute(dag)

        assert isinstance(result, PartialResult)
        assert "search" in result.error.lower() or "failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_skips_dependent_steps_on_failure(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test that dependent steps are skipped when a dependency fails."""
        # Make search agent fail
        search_agent = mock_registry.get_agent("search")
        search_agent.execute = AsyncMock(
            return_value=TaskResult(
                success=False,
                error="Search failed",
            )
        )

        dag = ExecutionDAG(
            goal="Search and summarize",
            steps=[
                DAGStep(
                    id="search",
                    agent_name="search",
                    description="Search",
                    input_template={},
                ),
                DAGStep(
                    id="summarize",
                    agent_name="summarize",
                    description="Summarize",
                    input_template={},
                    depends_on=["search"],
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        await executor.execute(dag)

        # Summarize should not have been called
        summarize_agent = mock_registry.get_agent("summarize")
        summarize_agent.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_missing_agent_returns_error(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test handling when agent doesn't exist."""
        dag = ExecutionDAG(
            goal="Test",
            steps=[
                DAGStep(
                    id="unknown",
                    agent_name="nonexistent_agent",
                    description="This agent doesn't exist",
                    input_template={},
                ),
            ],
        )
        executor = DAGExecutor(registry=mock_registry, session=session)

        result = await executor.execute(dag)

        assert isinstance(result, PartialResult)
        assert "nonexistent" in result.error.lower() or "not found" in result.error.lower()


class TestDAGExecutorVariableResolution:
    """Tests for variable resolution in DAGExecutor."""

    @pytest.fixture
    def mock_registry(self) -> AgentRegistry:
        """Create a mock registry."""
        registry = AgentRegistry()
        agent = MagicMock()
        agent.name = "test"
        agent.capabilities = ["test"]
        agent.execute = AsyncMock(
            return_value=TaskResult(
                success=True,
                data={"value": "test_output"},
            )
        )
        registry.register(agent)
        return registry

    @pytest.fixture
    def session(self) -> Session:
        """Create a session with some data."""
        session = Session()
        session.store("search", {"video_id": "abc123", "title": "Test Video"})
        session.store("results", [{"id": "1"}, {"id": "2"}])
        return session

    def test_resolve_simple_variable(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test resolving a simple variable reference."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        template = {"video_id": "$search.video_id"}
        resolved = executor._resolve_variables(template)

        assert resolved["video_id"] == "abc123"

    def test_resolve_nested_variable(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test resolving nested dictionary access."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        template = {"title": "$search.title"}
        resolved = executor._resolve_variables(template)

        assert resolved["title"] == "Test Video"

    def test_resolve_array_index(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test resolving array index access."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        template = {"first_id": "$results[0].id"}
        resolved = executor._resolve_variables(template)

        assert resolved["first_id"] == "1"

    def test_resolve_mixed_template(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test resolving template with mixed literal and variable values."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        template = {
            "video_id": "$search.video_id",
            "format": "mp4",
            "quality": "high",
        }
        resolved = executor._resolve_variables(template)

        assert resolved["video_id"] == "abc123"
        assert resolved["format"] == "mp4"
        assert resolved["quality"] == "high"

    def test_resolve_missing_variable_raises(
        self, mock_registry: AgentRegistry, session: Session
    ) -> None:
        """Test that missing variable raises error."""
        executor = DAGExecutor(registry=mock_registry, session=session)

        template = {"missing": "$nonexistent.field"}

        with pytest.raises(KeyError):
            executor._resolve_variables(template)


# ============================================================================
# PlannerAgent Tests
# ============================================================================


class TestPlannerAgent:
    """Tests for PlannerAgent."""

    @pytest.fixture
    def mock_registry(self) -> AgentRegistry:
        """Create a mock registry with test agents."""
        registry = AgentRegistry()

        for name, caps, desc in [
            ("search", ["youtube_search"], "Searches YouTube"),
            ("transcript", ["transcript_fetch"], "Gets transcripts"),
            ("summarize", ["summarization"], "Summarizes text"),
        ]:
            agent = MagicMock()
            agent.name = name
            agent.capabilities = caps
            agent.description = desc
            registry.register(agent)

        return registry

    @pytest.mark.asyncio
    async def test_create_plan_returns_dag(self, mock_registry: AgentRegistry) -> None:
        """Test that create_plan returns a valid ExecutionDAG."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        # Mock the chat client
        mock_client = MagicMock()

        with patch("youtube_agent_planner.agents.planner.Agent") as MockChatAgent:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(
                return_value=MagicMock(
                    text="""```json
{
    "goal": "Find and summarize a video",
    "steps": [
        {
            "id": "search",
            "agent": "search",
            "description": "Search for videos",
            "input": {"query": "python tutorials"},
            "depends_on": []
        },
        {
            "id": "summarize",
            "agent": "summarize",
            "description": "Summarize the video",
            "input": {"text": "$search.text"},
            "depends_on": ["search"]
        }
    ]
}
```"""
                )
            )
            MockChatAgent.return_value = mock_agent

            planner = PlannerAgent(registry=mock_registry, client=mock_client)
            dag = await planner.create_plan("Find and summarize a Python tutorial")

            assert isinstance(dag, ExecutionDAG)
            assert len(dag.steps) == 2
            assert dag.get_step("search") is not None
            assert dag.get_step("summarize").depends_on == ["search"]

    def test_create_simple_plan(self, mock_registry: AgentRegistry) -> None:
        """Test creating a plan programmatically (no LLM)."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        mock_client = MagicMock()
        planner = PlannerAgent(registry=mock_registry, client=mock_client)

        steps = [
            {"id": "search", "agent": "search", "input": {"query": "test"}},
            {
                "id": "summarize",
                "agent": "summarize",
                "input": {"text": "$search"},
                "depends_on": ["search"],
            },
        ]
        dag = planner.create_simple_plan(steps, goal="Test plan")

        assert dag.goal == "Test plan"
        assert len(dag.steps) == 2

    def test_parse_dag_response_extracts_json(self, mock_registry: AgentRegistry) -> None:
        """Test that _parse_dag_response correctly extracts JSON from markdown."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        mock_client = MagicMock()
        planner = PlannerAgent(registry=mock_registry, client=mock_client)

        response_text = """Here's the plan:

```json
{
    "goal": "Test",
    "steps": [
        {"id": "a", "agent": "search", "description": "A", "input": {}, "depends_on": []}
    ]
}
```

This plan will work well."""

        dag = planner._parse_dag_response(response_text, "fallback goal")

        assert dag.goal == "Test"
        assert len(dag.steps) == 1

    def test_parse_dag_response_invalid_json_raises(
        self, mock_registry: AgentRegistry
    ) -> None:
        """Test that invalid JSON raises ValueError."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        mock_client = MagicMock()
        planner = PlannerAgent(registry=mock_registry, client=mock_client)

        with pytest.raises(ValueError, match="Failed to parse"):
            planner._parse_dag_response("not valid json", "goal")

    def test_parse_dag_response_missing_steps_raises(
        self, mock_registry: AgentRegistry
    ) -> None:
        """Test that missing steps field raises ValueError."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        mock_client = MagicMock()
        planner = PlannerAgent(registry=mock_registry, client=mock_client)

        with pytest.raises(ValueError, match="missing 'steps'"):
            planner._parse_dag_response('{"goal": "test"}', "goal")

    @pytest.mark.asyncio
    async def test_replan_creates_revised_dag(self, mock_registry: AgentRegistry) -> None:
        """Test that replan creates a revised DAG after failure."""
        from youtube_agent_planner.agents.planner import PlannerAgent

        mock_client = MagicMock()

        with patch("youtube_agent_planner.agents.planner.Agent") as MockChatAgent:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(
                return_value=MagicMock(
                    text="""```json
{
    "goal": "Alternative approach",
    "steps": [
        {
            "id": "alt_step",
            "agent": "summarize",
            "description": "Try different approach",
            "input": {"text": "cached data"},
            "depends_on": []
        }
    ]
}
```"""
                )
            )
            MockChatAgent.return_value = mock_agent

            planner = PlannerAgent(registry=mock_registry, client=mock_client)
            revised_dag = await planner.replan(
                original_goal="Original goal",
                completed_results={"search": {"data": "some data"}},
                failed_step="transcript",
                error="API timeout",
            )

            assert isinstance(revised_dag, ExecutionDAG)
            assert len(revised_dag.steps) == 1
            assert revised_dag.get_step("alt_step") is not None
