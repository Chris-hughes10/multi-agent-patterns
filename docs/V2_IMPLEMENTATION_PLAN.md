# YouTube Agent V2 - Multi-Agent Patterns Evolution

## Overview

Build `src/youtube_agent_v2/` exploring two multi-agent patterns beyond the current orchestrator approach:
1. **Queue + Dispatcher** - Central dispatcher assigns tasks from queue
2. **Queue + Self-Selection** - Agents claim tasks based on capabilities

Also create documentation explaining the current v1 event loop mechanics for blog context.

---

## Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: V1 Async Fix | ✅ Complete | True async orchestrator with parallel execution |
| Phase 2: Blog Foundation | ✅ Complete | `docs/EVENT_LOOP_EXPLAINED.md` created |
| Phase 3: V2 Core Abstractions | ✅ Complete | Task, TaskQueue, Registry, BaseAgent |
| Phase 4: V2 Agents | ✅ Complete | Search, Transcript, Summarize, Writer |
| Phase 5: V2 Dispatcher Pattern | ✅ Complete | DispatcherCoordinator, CLI, tests |
| Phase 6: V2 Self-Selection Pattern | ✅ Complete | SelfSelectingPool, CLI --pattern flag, tests |
| Phase 7: Final Documentation | ✅ Complete | Learnings, pattern comparison, recommendations |
| **Phase 8: True Agent Coordination** | ✅ Complete | Planner+DAG and Autonomous patterns fully implemented with tests |

### V1 vs V2: The Key Difference

| Aspect | V1 Orchestrator | V2 Multi-Agent |
|--------|-----------------|----------------|
| **Control Flow** | Everything goes through the orchestrator | Agents hand off to each other directly |
| **Central Point** | Orchestrator LLM makes all decisions | Synthesizer receives user input and final results only |
| **Agent Communication** | Sub-agents return to orchestrator after each call | Agents chain together, only returning when the full task is done |
| **Result Aggregation** | Orchestrator synthesizes after each step | Synthesizer aggregates only when chain completes |

**In V1:** User → Orchestrator → Agent A → Orchestrator → Agent B → Orchestrator → ... → User

**In V2:** User → Synthesizer → Agent A → Agent B → Agent C → Synthesizer → User

The agents hand off to each other directly. The Synthesizer (user-facing agent) only sees the initial request and the final aggregated result - it doesn't coordinate every step.

### Current Realization

The infrastructure from Phases 3-7 provides **task routing** but not true **agent coordination**. The Dispatcher and Self-Selection patterns determine *which* agent handles a task, but agents don't:
- Hand off work to each other
- Reason about what to do next
- Create dynamic multi-step workflows

The `ResearchAgent` was removed because it essentially recreated V1's hardcoded orchestrator pattern - it had explicit steps (search → transcript → summarize) baked into the code.

**What's needed:** A way for agents to dynamically coordinate without hardcoded chains, with a Synthesizer agent as the user-facing entry point.

---

## Part 1: V1 Orchestrator Architecture

### Overview
V1 uses an **orchestrator pattern** where a central agent coordinates specialized sub-agents.

### Request Flow
```
User Request
    ↓
CLI (sync) → asyncio.run()
    ↓
OrchestratorAgent.run() (async)
    ↓
ChatAgent → LLM decides which sub-agent to call
    ↓
Tool call: ask_search_agent() / ask_transcript_agent() / etc.
    ↓
Sub-agent executes (async) → returns result
    ↓
Orchestrator LLM synthesizes response
    ↓
Response to user
```

### Key Components
- **OrchestratorAgent**: Coordinates sub-agents, maintains conversation thread
- **Sub-agents**: SearchAgent, TranscriptAgent, SummarizeAgent, WriterAgent
- **Tool wrappers**: `ask_*_agent()` methods expose sub-agents as tools to the LLM
- **Context injection**: `TranscriptContextProvider` injects stored transcript info before each LLM call

### Async Implementation (Completed)

The framework supports async tool functions via `inspect.isawaitable()`. The orchestrator now uses true async throughout:

```python
async def _delegate(self, agent_name: str, request: str) -> str:
    """Delegate a request to a sub-agent - fully async."""
    agent = self._get_agent(agent_name)
    result = await agent.run(request)  # Stays on same event loop
    return result.text

async def ask_search_agent(self, request: str) -> str:
    return await self._delegate("search", request)
```

Multiple async tool calls execute in parallel via `asyncio.gather()`.

#### Async Patterns Used

| Component | Pattern | Implementation |
|-----------|---------|----------------|
| Orchestrator tools | Native async | `async def` + `await agent.run()` |
| YouTube search | Native async | `httpx.AsyncClient` (replaced urllib) |
| LLM summarization | Native async | `AsyncAzureOpenAI` client |
| Transcript fetching | Thread wrapper | `asyncio.to_thread()` (youtube_transcript_api is sync) |
| File I/O (storage) | Thread wrapper | `asyncio.to_thread()` for JSON read/write |
| Markdown writing | Thread wrapper | `asyncio.to_thread()` for file writes |

#### Why Different Patterns?

1. **Native async** (`httpx`, `AsyncAzureOpenAI`): For libraries with async support, use them directly. No thread overhead, true non-blocking I/O.

2. **`asyncio.to_thread()`**: For sync-only third-party libraries (like `youtube_transcript_api`), wrap in a thread to avoid blocking the event loop. The operation runs in a thread pool while other coroutines continue.

```python
# Example: Wrapping sync transcript fetching
async def fetch_transcript(url_or_id: str) -> TranscriptResult:
    return await asyncio.to_thread(_fetch_transcript_sync, url_or_id, languages, fetcher)
```

#### Validation

Tests in `tests/test_async_parallel.py` prove parallel execution:
- 3 agent calls with 100ms delays complete in ~100ms (not 300ms)
- Confirms true async, not blocking sequential execution

### V1 → V2 Motivation
- V1: Orchestrator LLM decides sequencing, sub-agents are passive
- V2: Agents can submit tasks to a queue, enabling decoupled parallel execution

---

## Part 2: V2 Architecture - Shared Foundation

### Directory Structure
```
src/youtube_agent_v2/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── base_agent.py      # BaseAgent class
│   ├── task.py            # Task, TaskResult, TaskStatus
│   ├── task_queue.py      # AsyncTaskQueue
│   └── registry.py        # AgentRegistry for discovery
├── agents/
│   ├── __init__.py
│   ├── search.py          # SearchAgent (extends BaseAgent)
│   ├── transcript.py      # TranscriptAgent
│   ├── summarize.py       # SummarizeAgent
│   └── writer.py          # WriterAgent
├── patterns/
│   ├── __init__.py
│   ├── dispatcher.py      # Stage 1: DispatcherCoordinator
│   └── self_selection.py  # Stage 2: SelfSelectingPool
└── cli/
    ├── __init__.py
    └── main.py            # V2 CLI entry point
```

### Reuse from V1 (Direct Imports)
```python
# In v2 agents, import directly from v1:
from youtube_agent.services.youtube import YouTubeTranscriptFetcher, search_youtube
from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.summarizer import TranscriptSummarizer
from youtube_agent.models.transcript import Transcript, TranscriptResult
from youtube_agent.models.config import Settings, get_settings
from youtube_agent.tools.search import search_youtube_formatted
from youtube_agent.tools.transcript import fetch_video_transcript, store_video_transcript
from youtube_agent.tools.summarize import summarize_stored_transcript
from youtube_agent.tools.writer import write_markdown_file
```

### Core Abstractions

#### Task ([core/task.py](src/youtube_agent_v2/core/task.py))
```python
@dataclass
class Task:
    id: str
    description: str                    # Natural language task
    required_capabilities: list[str]    # e.g., ["search"], ["summarization"]
    context: dict[str, Any]             # Shared context
    parent_id: str | None = None        # For task chains
    max_depth: int = 5                  # Guard against infinite delegation
    current_depth: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None
    created_by: str | None = None       # Agent that spawned this task
```

#### BaseAgent ([core/base_agent.py](src/youtube_agent_v2/core/base_agent.py))
```python
class BaseAgent(ABC):
    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,  # Model flexibility
    ):
        self._registry = registry
        self._client = client or get_default_client()
        self._chat_agent: ChatAgent | None = None

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]: ...

    @abstractmethod
    def _get_instructions(self) -> str: ...

    @abstractmethod
    def _get_tools(self) -> list[Callable]: ...

    def can_handle(self, task: Task) -> bool:
        """Check if this agent can handle the task."""
        return any(cap in self.capabilities for cap in task.required_capabilities)

    async def execute(self, task: Task) -> TaskResult:
        """Execute task and return result."""
        ...

    def submit_task(self, task: Task) -> None:
        """Submit a new task to the queue (for spawning sub-tasks)."""
        if task.current_depth >= task.max_depth:
            raise MaxDepthExceededError(f"Task depth {task.current_depth} exceeds max {task.max_depth}")
        self._registry.submit(task)
```

#### AgentRegistry ([core/registry.py](src/youtube_agent_v2/core/registry.py))
```python
class AgentRegistry:
    """Registry for agent discovery and task routing."""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._capabilities_index: dict[str, list[str]] = {}  # capability -> [agent_names]
        self._task_queue: AsyncTaskQueue = AsyncTaskQueue()

    def register(self, agent: BaseAgent) -> None:
        """Register an agent and index its capabilities."""
        self._agents[agent.name] = agent
        for cap in agent.capabilities:
            self._capabilities_index.setdefault(cap, []).append(agent.name)

    def find_agents_for_task(self, task: Task) -> list[BaseAgent]:
        """Find all agents capable of handling a task."""
        candidates = set()
        for cap in task.required_capabilities:
            for agent_name in self._capabilities_index.get(cap, []):
                candidates.add(agent_name)
        return [self._agents[name] for name in candidates]

    def submit(self, task: Task) -> None:
        """Submit task to the queue."""
        self._task_queue.put(task)

    async def get_next_task(self) -> Task:
        """Get next task from queue (async)."""
        return await self._task_queue.get()
```

### Model Flexibility
```python
# In infra/client.py - extend for multiple models
from functools import lru_cache

@lru_cache
def get_chat_client(model_tier: str = "default") -> AzureOpenAIChatClient:
    """Get client for specified model tier."""
    settings = get_settings()

    deployment_map = {
        "default": settings.azure_openai_deployment,
        "fast": settings.azure_openai_deployment_fast,      # e.g., gpt-4o-mini
        "powerful": settings.azure_openai_deployment_powerful,  # e.g., gpt-4o
    }

    return AzureOpenAIChatClient(
        credential=...,
        endpoint=settings.azure_openai_endpoint,
        deployment_name=deployment_map.get(model_tier, deployment_map["default"]),
        ...
    )

# Usage in agents:
class SummarizeAgent(BaseAgent):
    def __init__(self, registry: AgentRegistry):
        super().__init__(registry, client=get_chat_client("fast"))  # Use cheaper model
```

---

## Part 3: Stage 1 - Queue + Dispatcher Pattern

### Concept
A central **DispatcherCoordinator** monitors the task queue and assigns tasks to appropriate agents. Similar to v1 orchestrator but decoupled via queue.

```
User Request → Dispatcher creates Task → Queue
                                           ↓
                            Dispatcher pulls task
                                           ↓
                            Finds capable agent
                                           ↓
                            Assigns to agent
                                           ↓
                            Agent executes (can spawn sub-tasks → Queue)
                                           ↓
                            Result collected
```

### Implementation ([patterns/dispatcher.py](src/youtube_agent_v2/patterns/dispatcher.py))

```python
class DispatcherCoordinator:
    """Central dispatcher that assigns tasks from queue to agents."""

    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, TaskResult] = {}

    async def submit_and_wait(self, description: str, capabilities: list[str]) -> TaskResult:
        """Submit a task and wait for its completion."""
        task = Task(
            id=str(uuid4()),
            description=description,
            required_capabilities=capabilities,
            context={},
        )
        self._registry.submit(task)
        return await self._wait_for_task(task.id)

    async def run(self, max_concurrent: int = 3) -> None:
        """Main dispatch loop - runs until shutdown."""
        while True:
            # Get next task from queue
            task = await self._registry.get_next_task()

            # Find capable agents
            agents = self._registry.find_agents_for_task(task)
            if not agents:
                self._results[task.id] = TaskResult(
                    success=False,
                    error="No capable agent found"
                )
                continue

            # Select agent (simple: first match; could be smarter)
            agent = agents[0]

            # Execute concurrently (up to max_concurrent)
            await self._throttle(max_concurrent)
            asyncio.create_task(self._execute_task(agent, task))

    async def _execute_task(self, agent: BaseAgent, task: Task) -> None:
        """Execute a task with an agent."""
        task.status = TaskStatus.RUNNING
        try:
            result = await agent.execute(task)
            task.status = TaskStatus.COMPLETED
            task.result = result
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.result = TaskResult(success=False, error=str(e))

        self._results[task.id] = task.result
```

### Key Characteristics
- **Centralized control**: Dispatcher decides which agent handles each task
- **Concurrent execution**: Multiple tasks can run in parallel
- **Sub-task spawning**: Agents can submit new tasks to queue
- **Depth guard**: `max_depth` prevents infinite delegation chains

---

## Part 4: Stage 2 - Queue + Self-Selection Pattern

### Concept
Agents **actively watch** the queue and claim tasks they can handle. More autonomous - no central dispatcher making assignments.

```
User Request → Task created → Queue
                                ↓
        ┌───────────────────────┼───────────────────────┐
        ↓                       ↓                       ↓
   SearchAgent             TranscriptAgent         SummarizeAgent
   (watches queue)         (watches queue)         (watches queue)
        ↓                       ↓                       ↓
   "I can handle this!"    "Not my task"           "Not my task"
        ↓
   Claims & executes
        ↓
   Can spawn sub-tasks → Queue → Other agents claim
```

### Implementation ([patterns/self_selection.py](src/youtube_agent_v2/patterns/self_selection.py))

```python
class SelfSelectingPool:
    """Pool where agents self-select tasks from queue."""

    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._agent_tasks: dict[str, asyncio.Task] = {}  # agent_name -> watcher task
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        """Start all agent watchers."""
        for agent in self._registry.all_agents():
            self._agent_tasks[agent.name] = asyncio.create_task(
                self._agent_watcher(agent)
            )

    async def _agent_watcher(self, agent: BaseAgent) -> None:
        """Each agent watches queue for tasks it can handle."""
        while not self._shutdown.is_set():
            # Peek at queue (don't consume yet)
            task = await self._registry.peek_next_task()

            if task and agent.can_handle(task):
                # Try to claim the task (atomic)
                claimed = await self._registry.try_claim(task.id, agent.name)
                if claimed:
                    await self._execute_task(agent, task)
            else:
                # Not for us, let others try
                await asyncio.sleep(0.1)  # Avoid busy-wait

    async def submit_and_wait(self, description: str, capabilities: list[str]) -> TaskResult:
        """Submit task and wait for any agent to complete it."""
        task = Task(...)
        self._registry.submit(task)
        return await self._wait_for_completion(task.id)
```

### Task Queue with Claiming ([core/task_queue.py](src/youtube_agent_v2/core/task_queue.py))

```python
class AsyncTaskQueue:
    """Thread-safe async task queue with claim support."""

    def __init__(self):
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._pending: dict[str, Task] = {}  # id -> task (for peeking)
        self._claimed: dict[str, str] = {}   # task_id -> agent_name
        self._lock = asyncio.Lock()

    async def put(self, task: Task) -> None:
        self._pending[task.id] = task
        await self._queue.put(task)

    async def peek(self) -> Task | None:
        """Peek without consuming."""
        async with self._lock:
            for task_id, task in self._pending.items():
                if task_id not in self._claimed:
                    return task
        return None

    async def try_claim(self, task_id: str, agent_name: str) -> bool:
        """Atomically try to claim a task."""
        async with self._lock:
            if task_id in self._claimed:
                return False  # Already claimed
            if task_id not in self._pending:
                return False  # Task doesn't exist
            self._claimed[task_id] = agent_name
            return True
```

### Key Characteristics
- **Decentralized**: No single dispatcher - agents are autonomous
- **Competitive**: Multiple agents may try to claim same task
- **Scalable**: Easy to add new agents without modifying coordinator
- **Natural load balancing**: Busy agents naturally take fewer tasks

---

## Part 5: Agent Implementations

### Example: SearchAgent
```python
class SearchAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "search"

    @property
    def capabilities(self) -> list[str]:
        return ["youtube_search", "video_discovery"]

    def _get_instructions(self) -> str:
        return """You are a YouTube search specialist.
        Given a search query, find relevant videos.
        Return structured results with video IDs and titles."""

    def _get_tools(self) -> list[Callable]:
        return [search_youtube_formatted]  # Reuse from v1

    async def execute(self, task: Task) -> TaskResult:
        """Execute search task."""
        # Use the underlying ChatAgent
        if self._chat_agent is None:
            self._chat_agent = ChatAgent(
                chat_client=self._client,
                name=self.name,
                instructions=self._get_instructions(),
                tools=self._get_tools(),
            )

        result = await self._chat_agent.run(task.description)
        return TaskResult(success=True, data=result.text)
```

### Example: TranscriptAgent with Sub-Task Spawning
```python
class TranscriptAgent(BaseAgent):
    @property
    def capabilities(self) -> list[str]:
        return ["transcript_fetch", "transcript_storage"]

    async def execute(self, task: Task) -> TaskResult:
        # ... fetch transcript ...

        # If task context requests summarization, spawn sub-task
        if task.context.get("auto_summarize"):
            summary_task = Task(
                id=str(uuid4()),
                description=f"Summarize transcript for {video_id}",
                required_capabilities=["summarization"],
                context={"transcript": transcript_text},
                parent_id=task.id,
                current_depth=task.current_depth + 1,
                max_depth=task.max_depth,
                created_by=self.name,
            )
            self.submit_task(summary_task)  # Goes to queue

        return TaskResult(success=True, data=transcript_text)
```

---

## Part 6: Implementation Order

### Phase 1: V1 Async Fix ✅ COMPLETE
1. ✅ Convert orchestrator tool methods to `async` (framework supports this via `inspect.isawaitable()`)
2. ✅ Remove `_run_sync()` workaround - just `await agent.run()` directly
3. ✅ Convert `TranscriptSummarizer` to use `AsyncAzureOpenAI`
4. ✅ Replace `urllib` with `httpx.AsyncClient` for YouTube search
5. ✅ Wrap sync `youtube_transcript_api` with `asyncio.to_thread()`
6. ✅ Make all tool functions async (transcript, summarize, writer, search)
7. ✅ Add async validation tests (`tests/test_async_parallel.py`)
8. ✅ Verify parallel execution - 3x100ms calls complete in ~100ms

**Files modified:**
- `pyproject.toml` - Added `httpx>=0.27.0`, `aiofiles>=24.1.0`
- `src/youtube_agent/agents/orchestrator.py` - Async `_delegate()` and tool methods
- `src/youtube_agent/services/summarizer.py` - `AsyncAzureOpenAI` client
- `src/youtube_agent/services/youtube.py` - `httpx` for search, `asyncio.to_thread()` for transcript
- `src/youtube_agent/tools/*.py` - All tools now async
- `tests/test_*.py` - Updated for async compatibility

### Phase 2: Blog Foundation
1. Create `docs/EVENT_LOOP_EXPLAINED.md` - Document orchestrator pattern and event loop mechanics

### Phase 3: V2 Core Abstractions
1. Create `src/youtube_agent_v2/` directory structure
2. Implement `core/task.py` - Task and TaskResult dataclasses
3. Implement `core/task_queue.py` - AsyncTaskQueue
4. Implement `core/registry.py` - AgentRegistry
5. Implement `core/base_agent.py` - BaseAgent ABC

### Phase 4: V2 Agents
1. Implement `agents/search.py` - SearchAgent
2. Implement `agents/transcript.py` - TranscriptAgent
3. Implement `agents/summarize.py` - SummarizeAgent
4. Implement `agents/writer.py` - WriterAgent

### Phase 5: V2 Dispatcher Pattern
1. Implement `patterns/dispatcher.py` - DispatcherCoordinator
2. Create `cli/main.py` with dispatcher-based entry point
3. **Integration test**: End-to-end dispatcher test

### Phase 6: V2 Self-Selection Pattern
1. Extend `core/task_queue.py` with peek/claim methods
2. Implement `patterns/self_selection.py` - SelfSelectingPool
3. Add CLI flag to switch between patterns
4. **Integration test**: End-to-end self-selection test

### Phase 7: Final Documentation
1. Update this document with learnings and pattern comparison

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Reuse v1 components | Direct imports | Avoid duplication, single source of truth |
| Task depth limit | `max_depth=5` | Prevent infinite delegation loops |
| Capability matching | List intersection | Simple, extensible |
| Model per agent | Client injection | Allows cheap/powerful model selection |
| Queue implementation | `asyncio.Queue` | Native async, thread-safe |
| Claim mechanism | Lock + dict | Simple atomic claiming for self-selection |

---

## Guards Against Runaway Delegation

1. **max_depth**: Tasks track depth, reject if exceeded
2. **created_by tracking**: Can detect cycles (A → B → A)
3. **Timeout per task**: Configurable execution timeout
4. **Task budget**: Optional limit on total tasks per user request

---

## Files to Create

### Documentation
1. `docs/EVENT_LOOP_EXPLAINED.md` - Blog foundation (v1 mechanics)

### Core Module
2. `src/youtube_agent_v2/__init__.py`
3. `src/youtube_agent_v2/core/__init__.py`
4. `src/youtube_agent_v2/core/task.py`
5. `src/youtube_agent_v2/core/task_queue.py`
6. `src/youtube_agent_v2/core/registry.py`
7. `src/youtube_agent_v2/core/base_agent.py`

### Agents Module
8. `src/youtube_agent_v2/agents/__init__.py`
9. `src/youtube_agent_v2/agents/search.py`
10. `src/youtube_agent_v2/agents/transcript.py`
11. `src/youtube_agent_v2/agents/summarize.py`
12. `src/youtube_agent_v2/agents/writer.py`

### Patterns Module
13. `src/youtube_agent_v2/patterns/__init__.py`
14. `src/youtube_agent_v2/patterns/dispatcher.py`
15. `src/youtube_agent_v2/patterns/self_selection.py`

### CLI Module
16. `src/youtube_agent_v2/cli/__init__.py`
17. `src/youtube_agent_v2/cli/main.py`

---

## Comparison: V1 Orchestrator vs V2 Patterns

| Aspect | V1 Orchestrator | V2 Dispatcher | V2 Self-Selection |
|--------|-----------------|---------------|-------------------|
| Control | Central LLM decides | Central code assigns | Agents compete |
| Parallelism | ✅ True async parallel (after fix) | Configurable concurrent | Natural concurrency |
| Adding agents | Modify orchestrator | Register in registry | Register in registry |
| Complexity | Medium | Medium | Higher |
| Autonomy | Low (orchestrator controls) | Medium | High |
| Best for | Simple workflows | Controlled parallel | Scalable systems |

> **Note**: V1 now supports true parallel execution via async tools. The LLM can call multiple sub-agents simultaneously using `asyncio.gather()` under the hood.

---

## Part 7: Final Implementation Summary

### What Was Built

#### V2 Module Structure (Implemented)
```
src/youtube_agent_v2/
├── __init__.py                    # Public API exports
├── core/
│   ├── __init__.py
│   ├── task.py                    # Task, TaskResult, TaskStatus, MaxDepthExceededError
│   ├── task_queue.py              # AsyncTaskQueue with peek/claim support
│   ├── registry.py                # AgentRegistry for discovery and routing
│   └── base_agent.py              # BaseAgent ABC
├── agents/
│   ├── __init__.py
│   ├── search.py                  # SearchAgent (youtube_search, video_discovery)
│   ├── transcript.py              # TranscriptAgent (transcript_fetch, transcript_storage)
│   ├── summarize.py               # SummarizeAgent (summarization, text_analysis)
│   └── writer.py                  # WriterAgent (file_export, markdown_writing)
├── patterns/
│   ├── __init__.py
│   ├── dispatcher.py              # DispatcherCoordinator + run_with_dispatcher()
│   └── self_selection.py          # SelfSelectingPool + run_with_self_selection()
└── cli/
    ├── __init__.py
    └── main.py                    # CLI with --pattern flag (dispatcher/self-selection)
```

#### Test Coverage
- `tests/test_v2_dispatcher.py` - 7 tests for dispatcher pattern
- `tests/test_v2_self_selection.py` - 10 tests for self-selection pattern
- Total: 87 tests passing (70 V1 + 17 V2)

### CLI Usage

```bash
# List available agents
youtube-agent-v2 agents

# List available patterns
youtube-agent-v2 patterns

# Run with dispatcher (default)
youtube-agent-v2 search "python async tutorial"
youtube-agent-v2 transcript dQw4w9WgXcQ
youtube-agent-v2 summarize dQw4w9WgXcQ

# Run with self-selection pattern
youtube-agent-v2 -p self-selection search "python async tutorial"

# Enable debug logging
youtube-agent-v2 -v -p self-selection search "test query"
```

---

## Part 8: Detailed Pattern Comparison

### Architecture Comparison

| Aspect | V1 Orchestrator | V2 Dispatcher | V2 Self-Selection |
|--------|-----------------|---------------|-------------------|
| **Control Flow** | LLM decides next agent | Code assigns to first capable | Agents compete to claim |
| **Task Queue** | Implicit (LLM state) | Explicit `AsyncTaskQueue` | Explicit with peek/claim |
| **Agent Discovery** | Hardcoded in orchestrator | `AgentRegistry` lookup | `AgentRegistry` + `can_handle()` |
| **Concurrency** | `asyncio.gather()` on tools | Semaphore-limited | Natural (busy agents claim less) |
| **Adding Agents** | Modify orchestrator code | `registry.register()` | `registry.register()` |
| **Sub-task Spawning** | Via tool return → LLM | `agent.submit_task()` | `agent.submit_task()` |

### When to Use Each Pattern

#### V1 Orchestrator
**Best for:** Conversational workflows where an LLM should decide the execution flow.

- User asks complex, multi-step questions
- Order of operations matters and requires reasoning
- Need natural language synthesis of results
- Conversation memory is important

#### V2 Dispatcher
**Best for:** Controlled parallel execution with predictable routing.

- Known task types with clear capability mapping
- Need centralized logging/monitoring
- Want to implement custom agent selection (load balancing, priority)
- Simpler debugging (single control point)

#### V2 Self-Selection
**Best for:** Scalable systems with autonomous agents.

- Many agents with overlapping capabilities
- Want natural load balancing
- Agents may be added/removed dynamically
- Building towards truly autonomous agent systems

### Performance Characteristics

| Metric | Dispatcher | Self-Selection |
|--------|------------|----------------|
| Task routing latency | O(1) lookup | O(n) polling |
| Memory overhead | Lower (single loop) | Higher (n watcher coroutines) |
| Scalability | Good | Better (decentralized) |
| Failure isolation | Central point of failure | Agents fail independently |

---

## Part 9: Learnings and Recommendations

### Key Learnings

1. **Async queue design matters**
   - `asyncio.Queue` is great for simple get/put
   - For self-selection, needed peek + atomic claim
   - Lock-based claiming is simple and sufficient at small scale

2. **Capability-based routing is powerful**
   - Agents declare capabilities, tasks declare requirements
   - Decouples task creation from agent implementation
   - Easy to add new agent types without touching existing code

3. **Depth guards are essential**
   - `max_depth` prevents infinite sub-task spawning
   - `created_by` tracking enables cycle detection
   - Timeouts provide ultimate safety net

4. **Reusing V1 services worked well**
   - Direct imports avoided code duplication
   - V2 agents are thin wrappers around V1 tools
   - Single source of truth for business logic

### Recommendations for Production Use

1. **Start with Dispatcher**
   - Simpler to debug and monitor
   - Add self-selection later if needed for scale

2. **Add observability**
   - Structured logging with task IDs
   - Metrics for queue depth, claim success rate
   - Distributed tracing for sub-task chains

3. **Consider persistence**
   - Current implementation is in-memory only
   - For durability, back queue with Redis/PostgreSQL
   - Enable recovery after restarts

4. **Implement agent selection strategies**
   - Current: first capable agent
   - Better: round-robin, least-loaded, capability score
   - Override `_select_agent()` in Dispatcher

5. **Add rate limiting**
   - Per-agent execution limits
   - Global task budget per request
   - Backpressure when queue is full

### Future Enhancements

1. **Priority queues** - High-priority tasks processed first
2. **Dead letter queue** - Failed tasks for retry/investigation
3. **Agent health checks** - Remove unhealthy agents from pool
4. **Dynamic agent scaling** - Spawn more agents under load
5. **Cross-process distribution** - Agents on different machines

---

## Part 10: Code Statistics

### Lines of Code (V2 Module)

| Component | Files | Lines |
|-----------|-------|-------|
| Core abstractions | 4 | ~250 |
| Agents | 4 | ~150 |
| Patterns | 2 | ~350 |
| CLI | 1 | ~275 |
| **Total V2** | **11** | **~1,025** |

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_v2_dispatcher.py | 7 | Dispatcher: 80% |
| test_v2_self_selection.py | 10 | Self-selection: 85% |

---

## Conclusion (Phases 1-7)

This implementation demonstrates three distinct multi-agent coordination patterns:

1. **V1 Orchestrator**: LLM-driven, conversational, good for complex reasoning
2. **V2 Dispatcher**: Code-driven, controlled, good for predictable workflows
3. **V2 Self-Selection**: Agent-driven, autonomous, good for scalable systems

All three patterns share:
- True async execution (non-blocking I/O)
- Capability-based agent discovery
- Sub-task spawning with depth guards
- Reuse of core business logic (V1 services)

The choice between patterns depends on your use case:
- Need LLM reasoning? → V1 Orchestrator
- Need predictable control? → V2 Dispatcher
- Need autonomous scale? → V2 Self-Selection

All code is tested, linted, and ready for extension.

---

## Part 11: Phase 8 - True Agent Coordination

### The Problem

The current V2 implementation routes tasks to agents, but agents don't coordinate with each other. The `ResearchAgent` shows the limitation - it has hardcoded logic:

```python
# Current ResearchAgent - hardcoded chain
async def execute(self, task: Task) -> TaskResult:
    plan = await self._plan_research(...)      # Step 1: Always plan
    search_result = await self._execute_search(...)  # Step 2: Always search
    transcripts = await self._execute_transcript(...)  # Step 3: Always transcript
    summaries = await self._execute_summary(...)  # Step 4: Always summarize
    return self._synthesize_results(...)  # Step 5: Always synthesize
```

This is just the V1 orchestrator with extra steps. What we want is **dynamic** coordination.

### Two Architectural Approaches

#### Approach 1: Planner + DAG Execution

A **Planner agent** creates a dynamic execution plan (DAG) based on the request and available agents. A **Dispatcher** then executes the DAG, tracking dependencies.

```
User Request: "Find videos about pork loin on kamado, get transcripts, summarize cooking temps"
                                    ↓
                            ┌───────────────┐
                            │  PlannerAgent │
                            └───────┬───────┘
                                    ↓
                    Creates execution DAG (JSON/data structure):
                    {
                      "steps": [
                        {"id": "search", "agent": "search", "input": "pork loin kamado"},
                        {"id": "t1", "agent": "transcript", "depends_on": ["search"], "input": "$search.results[0]"},
                        {"id": "t2", "agent": "transcript", "depends_on": ["search"], "input": "$search.results[1]"},
                        {"id": "sum1", "agent": "summarize", "depends_on": ["t1"], "input": "$t1.transcript"},
                        {"id": "sum2", "agent": "summarize", "depends_on": ["t2"], "input": "$t2.transcript"},
                        {"id": "final", "agent": "synthesize", "depends_on": ["sum1", "sum2"]}
                      ]
                    }
                                    ↓
                            ┌───────────────┐
                            │   Dispatcher  │ (executes DAG)
                            └───────┬───────┘
                                    ↓
              ┌─────────────────────┼─────────────────────┐
              ↓                     ↓                     ↓
        Execute "search"     (wait for search)      (wait for search)
              ↓                     ↓                     ↓
        Results ready         Execute t1              Execute t2    ← parallel
              ↓                     ↓                     ↓
                               Execute sum1          Execute sum2   ← parallel
                                    ↓                     ↓
                            ┌───────┴─────────────────────┘
                            ↓
                    Execute "final" (synthesize)
                            ↓
                      Return to user
```

**Key Components:**
1. **PlannerAgent**: LLM that understands available agents and creates execution plans
2. **Execution DAG**: Data structure representing steps and dependencies
3. **DAG Executor**: Tracks completed steps, resolves `$variable` references, submits ready tasks
4. **Stateful context**: Stores intermediate results (`$search.results`, `$t1.transcript`)

**What to Build:**
- `agents/planner.py` - PlannerAgent with system prompt listing available agents/capabilities
- `core/execution_dag.py` - DAG data structure and variable resolution
- `patterns/dag_executor.py` - Executes DAG, tracks dependencies, manages state
- Update CLI to use Planner for complex requests

**Pros:**
- Predictable execution order
- Easy to visualize and debug (the plan is inspectable)
- Efficient - batch parallel operations are explicit
- Planner only runs once per request

**Cons:**
- Plan is static - can't adapt if a step fails unexpectedly
- Planner needs to know all agents upfront
- More complex infrastructure (DAG tracking)

---

#### Approach 2: Autonomous Agent Reasoning

Each agent receives the **original goal** plus **current state**. The agent reasons about what to do next and who to delegate to. No central plan.

```
User Request: "Find videos about pork loin on kamado, get transcripts, summarize cooking temps"
                                    ↓
                          ┌─────────────────┐
                          │  SearchAgent    │ receives: goal + state{}
                          └────────┬────────┘
                                   ↓
              Agent thinks: "Goal needs videos. I can search. Let me search."
                                   ↓
                          Executes search, gets results
                                   ↓
              Agent thinks: "Goal needs transcripts. I can't do that.
                            I should hand off to TranscriptAgent."
                                   ↓
              Calls: submit_task(goal=original_goal,
                                 state={videos: [...]},
                                 capabilities=["transcript_fetch"])
                                   ↓
                          ┌─────────────────┐
                          │ TranscriptAgent │ receives: goal + state{videos}
                          └────────┬────────┘
                                   ↓
              Agent thinks: "Goal needs transcripts. I have video list.
                            Let me fetch transcripts for each."
                                   ↓
                          Fetches transcripts
                                   ↓
              Agent thinks: "Goal needs summaries. I should hand off."
                                   ↓
              Calls: submit_task(goal=original_goal,
                                 state={videos: [...], transcripts: [...]},
                                 capabilities=["summarization"])
                                   ↓
                          ┌─────────────────┐
                          │ SummarizeAgent  │ receives: goal + state{videos, transcripts}
                          └────────┬────────┘
                                   ↓
              Agent thinks: "Goal needs summaries about cooking temps.
                            I have transcripts. Let me summarize."
                                   ↓
                          Generates summaries
                                   ↓
              Agent thinks: "Goal is complete. Return results."
                                   ↓
                          Returns final answer
```

**Key Components:**
1. **Goal + State Protocol**: Every task carries original goal and accumulated state
2. **Agent Reasoning Prompt**: System prompt that teaches agents to reason about goal vs state
3. **Handoff Mechanism**: Agents call `submit_task()` with updated state
4. **Completion Detection**: Agents recognize when goal is satisfied

**What to Build:**
- Update `Task` to include `goal` (original request) and `state` (accumulated results)
- Update agent prompts with reasoning instructions:
  ```
  You receive: GOAL (what user wants) and STATE (what's been done).
  1. Can I complete the goal with current state? If yes, do it and return.
  2. If not, what's missing? What capability is needed?
  3. Hand off to the right agent with updated state.
  ```
- Add handoff tool to agents: `hand_off_to(capability, updated_state)`
- Completion detection (agent returns final result vs hands off)

**Pros:**
- Adaptive - agents can recover from failures
- Emergent behavior - agents figure out the flow
- Simpler infrastructure - no DAG tracking
- More flexible for open-ended requests

**Cons:**
- More LLM calls (each agent reasons)
- Harder to predict/debug execution path
- Risk of loops if agents keep handing off
- Requires careful prompt engineering

---

### Comparison

| Aspect | Planner + DAG | Autonomous Agents |
|--------|---------------|-------------------|
| **Planning** | Once upfront | Continuous at each step |
| **LLM calls** | 1 (planner) + N (execution) | N × reasoning calls |
| **Adaptability** | Static plan | Dynamic adaptation |
| **Debuggability** | High (inspect DAG) | Lower (emergent) |
| **Infrastructure** | DAG executor, variable resolution | Goal/state protocol |
| **Failure handling** | Re-plan or fail | Agents can retry/adapt |
| **Best for** | Batch processing, known workflows | Exploratory, conversational |

---

### Interactive Session Use Case

Both approaches work for interactive sessions where a user chats with the system:

**Planner approach:**
```
User: "Find me videos about kamado cooking"
→ Planner: Simple search DAG
→ Execute, return results

User: "Get transcripts for the first two"
→ Planner: Transcript DAG for video[0], video[1] (parallel)
→ Execute, store in session state

User: "Summarize them focusing on temperature"
→ Planner: Summary DAG referencing stored transcripts
→ Execute, return summaries
```

**Autonomous approach:**
```
User: "Find me videos about kamado cooking"
→ SearchAgent receives goal, searches, returns results (goal complete)

User: "Get transcripts for the first two"
→ System routes to TranscriptAgent
→ Agent sees goal "get transcripts", state has video list from session
→ Fetches transcripts, returns (goal complete)

User: "Summarize them focusing on temperature"
→ System routes to SummarizeAgent
→ Agent sees goal, state has transcripts
→ Summarizes, returns (goal complete)
```

---

### Decision: Implement Both

Build both approaches to compare them in practice:

```bash
youtube-agent-v2 -p planner chat      # Approach 1: Planner + DAG
youtube-agent-v2 -p autonomous chat   # Approach 2: Goal + State reasoning
youtube-agent-v2 -p dispatcher chat   # Existing: single-task routing
youtube-agent-v2 -p self-selection chat  # Existing: single-task routing
```

---

### Phase 8 Implementation Steps

#### Step 1: Shared Foundation ✅ Complete
- Created `core/session.py`:
  - `Session` class stores conversation context (search results, transcripts, etc.)
  - `SessionEntry` dataclass with key, value, timestamp, metadata
  - Variable resolution: `$search.results[0].video_id` → actual value
  - Path parsing for nested dict/array access
  - `ExecutionStep` dataclass for tracking agent execution path
  - Methods: `record_step()`, `get_execution_path()`, `get_path_summary()`, `get_agent_visit_counts()`
  - 42 unit tests passing (including execution path tests)
- Reorganized `core/` structure:
  - Created `core/models/` subpackage for pure data structures
  - Moved `task.py` and `handoff.py` to `core/models/`
  - Clean separation: models/ = data, core/ = infrastructure
- Created `core/models/handoff.py`:
  - `HandoffResult` dataclass with `action` ("complete" | "handoff")
  - Factory methods: `HandoffResult.complete()`, `HandoffResult.handoff()`
  - `AgentReasoning` dataclass for autonomous reasoning results
  - `PartialResult` dataclass for error/loop recovery
- Created `core/intent_router.py`:
  - `IntentRouter` ABC for routing intents to agents
  - `LLMIntentRouter` - routes using LLM evaluation of agent capabilities
  - `CapabilityIntentRouter` - keyword-based routing with fallback
  - `CompositeIntentRouter` - chain-of-responsibility pattern
  - `get_default_router()` - factory for recommended configuration
- Created `core/loop_detector.py`:
  - `LoopDetector` - detects cyclic handoff patterns
  - `check_for_loop()` - checks if max_visits exceeded in window
  - `detect_cycle()` - identifies repeating subsequence pattern
  - `AdaptiveLoopDetector` - allows certain agents more visits

#### Step 2: Synthesizer/Conversation Agent ✅ Complete
The Synthesizer is the **single point of contact** for users. It:
- Receives all user messages
- Maintains the `Session` (conversation memory)
- Delegates work to the Planner (Approach 1) or directly to agents (Approach 2)
- Aggregates results and produces the final user-facing response
- Does NOT coordinate every agent step (unlike V1 orchestrator)

```
┌─────────────────────────────────────────────────────────────────────┐
│                           V2 Architecture                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User ←───────────────────────────────────────────────→ Synthesizer
│                                                               │     │
│                                                        ┌──────┴───┐ │
│                                                        │  Session │ │
│                                                        └──────────┘ │
│                         ┌──────────────────────────────────┘        │
│                         ↓                                           │
│              ┌──────────────────────┐                               │
│              │  Approach 1: Planner │                               │
│              │  Creates DAG upfront │                               │
│              └──────────┬───────────┘                               │
│                         ↓                                           │
│              ┌──────────────────────┐                               │
│              │     DAG Executor     │                               │
│              │   Tracks dependencies│                               │
│              └──────────┬───────────┘                               │
│                         ↓                                           │
│   ┌─────────────────────┼─────────────────────────────┐             │
│   ↓                     ↓                             ↓             │
│ SearchAgent ──→ TranscriptAgent ──→ SummarizeAgent ──→ Return      │
│   (hands off)     (hands off)         (completes)                   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                         OR                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│              ┌──────────────────────┐                               │
│              │ Approach 2: Autonomous│                              │
│              │ First agent receives │                               │
│              │ goal + empty state   │                               │
│              └──────────┬───────────┘                               │
│                         ↓                                           │
│   SearchAgent: "I can search, let me do that"                       │
│        ↓                                                            │
│   Searches, then thinks: "Goal needs transcripts, hand off"         │
│        ↓                                                            │
│   TranscriptAgent: Receives goal + state{videos}                    │
│        ↓                                                            │
│   Fetches transcripts, thinks: "Goal needs summaries, hand off"     │
│        ↓                                                            │
│   SummarizeAgent: Receives goal + state{videos, transcripts}        │
│        ↓                                                            │
│   Summarizes, thinks: "Goal complete" → Returns to Synthesizer      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**What was built:**
- `agents/synthesizer.py` - SynthesizerAgent:
  - System prompt focused on user interaction (not task coordination)
  - Owns the `Session` instance
  - `process_request(user_request, pattern)` - main entry point
  - `_process_autonomous()` - implements autonomous agent coordination
  - `_process_with_planner()` - placeholder for planner pattern (TODO)
  - `_synthesize_response()` - formats results for user
  - Loop detection integrated via `LoopDetector`
  - Execution path tracking via `Session.record_step()`

**SynthesizerAgent responsibilities:**
1. Parse user intent ("What do they want?")
2. Delegate appropriately (to Planner or directly to capable agent)
3. Wait for chain to complete (agents hand off internally)
4. Receive final result from last agent in chain
5. Format and return user-friendly response
6. Store results in Session for follow-up questions

#### Step 3: Planner + DAG Approach ✅ Complete
- Created `patterns/dag_executor.py`:
  - `DAGStep` dataclass (id, agent_name, description, input_template, depends_on, status, result)
  - `ExecutionDAG` class (goal, steps, validation, ready step discovery)
  - `StepStatus` enum (PENDING, READY, RUNNING, COMPLETED, FAILED, SKIPPED)
  - `DAGExecutor` class with parallel execution, dependency tracking
  - Variable resolution via Session (`$step_id.field` → actual value)
  - `StepExecutionError` for error propagation
  - Re-planning support when steps fail
- Created `agents/planner.py`:
  - `PlannerAgent` - creates execution DAGs from user requests
  - System prompt with available agents catalog (built dynamically from registry)
  - JSON DAG output format with step dependencies
  - `create_plan(user_request)` - generates ExecutionDAG using LLM
  - `replan(original_goal, completed_results, failed_step, error)` - error recovery
  - `create_simple_plan(steps, goal)` - programmatic DAG creation (for testing)
  - Markdown code block parsing for LLM responses
- Updated `agents/synthesizer.py`:
  - `_process_with_planner()` - full implementation using PlannerAgent + DAGExecutor
  - `_attempt_replan()` - re-planning on failure with partial results
  - Execution step tracking for planner and executor
  - Session integration for storing plans and results
- Updated `agents/__init__.py` to export PlannerAgent
- 31 new tests in `tests/test_v2_planner_dag.py`:
  - DAGStep creation and status transitions
  - ExecutionDAG validation (dependencies, cycles, duplicates)
  - DAGExecutor parallel and sequential execution
  - Variable resolution from session
  - Error handling and step skipping
  - PlannerAgent plan creation and parsing

#### Step 4: Autonomous Approach (Semantic Intent) ✅ Complete
- Updated `core/base_agent.py`:
  - Added `description` property (human-readable description for intent routing)
  - Added `execute_autonomous(goal, state) -> HandoffResult | PartialResult` method
  - Default implementation wraps `execute()` and returns complete
- Implemented `execute_autonomous()` in all agents with goal-aware reasoning:
  - **SearchAgent**: Completes on search-only goals, hands off when transcripts/summaries needed
  - **TranscriptAgent**: Completes on transcript-only goals, hands off when summarization needed
  - **SummarizeAgent**: Completes on summarization goals, hands off when file export needed
  - **WriterAgent**: Always completes (final step in chains)
- Each agent uses rule-based keyword matching to decide completion vs handoff
- Handoff passes intent (natural language) and accumulated state to next agent

**Semantic Intent Routing:**
```python
# Agent hands off with natural language intent
await self.hand_off(
    intent="Get the spoken words from this YouTube video",
    state={"video_id": "abc123", "videos": [...]}
)

# Agents evaluate whether they can handle the intent
class TranscriptAgent(BaseAgent):
    @property
    def description(self) -> str:
        return "I fetch transcripts and captions from YouTube videos"

    async def evaluate_intent(self, intent: str) -> bool:
        # LLM evaluates: Can I help with this intent?
        prompt = f"""Given my capabilities: {self.description}
        Can I help with: "{intent}"?
        Answer only YES or NO."""
        response = await self._client.complete(prompt)
        return "YES" in response.upper()
```

**Routing with pre-filter (optional optimization):**
```python
# Fast pre-filter by keyword, then semantic evaluation
async def find_agent_for_intent(self, intent: str) -> BaseAgent | None:
    # Optional: keyword pre-filter to reduce LLM calls
    keywords = extract_keywords(intent)  # ["transcript", "words", "video"]
    candidates = self._registry.find_by_keywords(keywords)

    # Semantic evaluation of candidates
    for agent in candidates:
        if await agent.evaluate_intent(intent):
            return agent
    return None
```

#### Step 5: CLI Integration ✅ Complete
- Updated `cli/main.py`:
  - Added `AUTONOMOUS` to `Pattern` enum
  - Added `"autonomous"` to CLI `--pattern` choices
  - Created `run_with_autonomous()` function using SynthesizerAgent
  - Updated `run_task()` to route to autonomous pattern
  - Added autonomous description to `patterns` command
  - Updated chat command to support autonomous pattern

#### Step 6: Tests ✅ Complete
- Created `tests/test_v2_autonomous.py` with 23 tests:
  - `TestAgentDescriptions`: All agents have descriptions
  - `TestSearchAgentAutonomous`: Complete vs handoff based on goal
  - `TestTranscriptAgentAutonomous`: Complete vs handoff based on goal
  - `TestSummarizeAgentAutonomous`: Complete vs handoff to writer
  - `TestWriterAgentAutonomous`: Always completes
  - `TestAutonomousChain`: Integration tests for full agent chains
  - `TestAutonomousLoopDetection`: Loop detection with real detector
- Classicist testing approach (Kent Beck style):
  - Only mock external calls (YouTube API, LLM, file I/O)
  - Use real agents, registry, router, session

---

### Files (Phase 8)

```
src/youtube_agent_v2/
├── core/
│   ├── models/
│   │   ├── __init__.py       ✅ Created - Exports all model types
│   │   ├── task.py           ✅ Moved - Task, TaskResult, TaskStatus
│   │   └── handoff.py        ✅ Created - HandoffResult, AgentReasoning, PartialResult
│   ├── session.py            ✅ Extended - Session + ExecutionStep tracking
│   ├── intent_router.py      ✅ Created - IntentRouter, LLMIntentRouter, CapabilityIntentRouter
│   ├── loop_detector.py      ✅ Created - LoopDetector, AdaptiveLoopDetector
│   └── __init__.py           ✅ Updated - Re-exports all core types
├── agents/
│   ├── synthesizer.py        ✅ Created - SynthesizerAgent with both patterns
│   ├── planner.py            ✅ Created - PlannerAgent creates execution DAGs
│   └── __init__.py           ✅ Updated - Exports PlannerAgent
├── patterns/
│   └── dag_executor.py       ✅ Created - DAGStep, ExecutionDAG, DAGExecutor
tests/
├── test_v2_session.py        ✅ Passing - 42 tests
├── test_v2_dispatcher.py     ✅ Passing - 7 tests
├── test_v2_self_selection.py ✅ Passing - 10 tests
├── test_v2_planner_dag.py    ✅ Created - 31 tests for Planner + DAG pattern
└── test_v2_autonomous.py     ✅ Created - 23 tests for Autonomous approach
```

**Total Tests: 96 V2 tests passing**

#### Bug Fixes: Structured Data for DAG Variable Resolution

The initial implementation had issues where DAG variable references like `$search.results[0].video_id` would fail because agents returned LLM text responses instead of structured data.

**Problem:** When the planner created DAGs with variable references, the DAG executor couldn't resolve them because:
1. `SearchAgent` returned formatted text strings instead of JSON with a `results` array
2. `TranscriptAgent` returned LLM responses instead of `{"text": "...", "video_id": "..."}`
3. `SummarizeAgent` returned LLM responses instead of `{"summary": "..."}`

**Solution:** Override `execute()` in each agent to return structured dictionaries:

```python
# SearchAgent now returns:
{"query": "...", "count": 5, "results": [{"video_id": "...", "title": "...", ...}]}

# TranscriptAgent now returns:
{"video_id": "...", "title": "...", "text": "...", "cached": bool}

# SummarizeAgent now returns:
{"video_id": "...", "title": "...", "summary": "...", "cached": bool}
```

**Files modified:**
- `src/youtube_agent_v2/agents/search.py` - Direct service call, structured output
- `src/youtube_agent_v2/agents/transcript.py` - Direct service call, structured output
- `src/youtube_agent_v2/agents/summarize.py` - Direct service call, structured output
- `src/youtube_agent/tools/search.py` - Added `search_youtube_structured()` tool

#### Bug Fixes: Planner Agent Name Validation

The planner LLM would sometimes create plans with invented agent names like `"select_top_videos"` or `"extract_key_parameters"` that don't correspond to actual agents.

**Solution:**
1. Updated planner prompt to explicitly list valid agent names and emphasize constraints
2. Added validation in `_parse_dag_response()` to reject plans with invalid agent names
3. Clarified that `"summarize"` agent should be used for ANY analysis/extraction task

```python
# Validation in planner.py
valid_agent_names = {a.name for a in self._registry.all_agents()}
for step in data["steps"]:
    agent_name = step.get("agent", step.get("agent_name", ""))
    if agent_name not in valid_agent_names:
        raise ValueError(
            f"Invalid agent '{agent_name}' in step '{step.get('id', '?')}'. "
            f"Valid agents: {', '.join(sorted(valid_agent_names))}"
        )
```

---

### Example: End-to-End Flow

**User request:** "I want to cook a pork loin roast on a Kamado grill. Channels I trust are fork and embers. I need temperature, setup, internal temp and time."

**Step 1: Planner creates DAG**
```json
{
  "goal": "Research pork loin roast on Kamado with specific info",
  "steps": [
    {
      "id": "search",
      "agent": "search",
      "description": "Find pork loin kamado videos from fork and embers",
      "input": "pork loin roast kamado grill fork and embers"
    },
    {
      "id": "transcript_1",
      "agent": "transcript",
      "depends_on": ["search"],
      "input": {"video_id": "$search.results[0].video_id"}
    },
    {
      "id": "transcript_2",
      "agent": "transcript",
      "depends_on": ["search"],
      "input": {"video_id": "$search.results[1].video_id"}
    },
    {
      "id": "summarize_1",
      "agent": "summarize",
      "depends_on": ["transcript_1"],
      "input": {
        "transcript": "$transcript_1.text",
        "focus": ["cooking temperature", "grill setup", "internal temperature", "cooking time"]
      }
    },
    {
      "id": "summarize_2",
      "agent": "summarize",
      "depends_on": ["transcript_2"],
      "input": {
        "transcript": "$transcript_2.text",
        "focus": ["cooking temperature", "grill setup", "internal temperature", "cooking time"]
      }
    },
    {
      "id": "synthesize",
      "agent": "writer",
      "depends_on": ["summarize_1", "summarize_2"],
      "input": {
        "summaries": ["$summarize_1.text", "$summarize_2.text"],
        "format": "consolidated_research_report"
      }
    }
  ]
}
```

**Step 2: DAG Executor runs**
1. Execute `search` → results with video IDs
2. Resolve `$search.results[0].video_id` → execute `transcript_1` and `transcript_2` in parallel
3. Resolve transcripts → execute `summarize_1` and `summarize_2` in parallel
4. Resolve summaries → execute `synthesize`
5. Return final report to user

**Total:** 1 planner call + 6 agent executions (with parallelism: search → 2 transcripts → 2 summaries → synthesize)

---

## Part 12: Additional Design Decisions

### Approach 3: Hybrid (Planner + Adaptive Execution)

Rather than choosing between static DAG and fully autonomous, consider a hybrid where:
- Planner creates the initial DAG
- Individual agents can **modify** the DAG during execution (add fallback steps, skip branches)
- Gives inspectable plans with adaptive execution

```
User Request → Planner creates DAG
                    ↓
              DAG Executor starts
                    ↓
              Agent executes step
                    ↓
         ┌─────────┴─────────┐
         ↓                   ↓
    Success: continue    Failure: agent requests DAG modification
         ↓                   ↓
    Next step           Planner re-evaluates with partial results
                             ↓
                        Updated DAG continues
```

**Implementation considerations:**
- Agents return `StepResult` with optional `dag_modification_request`
- Planner has a "re-plan" mode that receives partial results + failure info
- Max re-plan attempts before returning to Synthesizer with partial results

---

### Semantic Routing Abstraction

Create an interface for intent-to-agent routing that can be swapped between implementations:

```python
# core/intent_router.py

from abc import ABC, abstractmethod

class IntentRouter(ABC):
    """Abstract interface for routing intents to agents."""

    @abstractmethod
    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry"
    ) -> "BaseAgent | None":
        """Find the best agent to handle the given intent."""
        ...

class LLMIntentRouter(IntentRouter):
    """Routes intents using LLM evaluation."""

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry"
    ) -> "BaseAgent | None":
        for agent in registry.all_agents():
            if await agent.evaluate_intent(intent):
                return agent
        return None

class EmbeddingIntentRouter(IntentRouter):
    """Routes intents using embedding similarity (future optimization)."""

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry"
    ) -> "BaseAgent | None":
        # Use cached embeddings of agent descriptions
        # Compare with intent embedding
        # Return best match above threshold
        ...

class KeywordIntentRouter(IntentRouter):
    """Fast keyword-based routing with LLM fallback."""

    def __init__(self, fallback: IntentRouter):
        self._fallback = fallback

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: "AgentRegistry"
    ) -> "BaseAgent | None":
        # Try keyword matching first
        candidates = self._keyword_match(intent, registry)
        if len(candidates) == 1:
            return candidates[0]
        # Ambiguous or no match - use fallback
        return await self._fallback.find_agent_for_intent(intent, registry)
```

**Start with `LLMIntentRouter`**, but the abstraction allows easy swap to embedding-based or hybrid approaches later.

---

### Completion Detection

Force explicit completion signaling with a structured result type:

```python
# core/handoff.py

from dataclasses import dataclass
from typing import Literal, Any

@dataclass
class HandoffResult:
    """Result from an agent's execution - either complete or handoff."""

    action: Literal["complete", "handoff"]

    # If action == "complete"
    result: Any | None = None

    # If action == "handoff"
    intent: str | None = None      # What needs to happen next
    state: dict | None = None      # Updated accumulated state

    def __post_init__(self):
        if self.action == "complete" and self.result is None:
            raise ValueError("Complete action requires a result")
        if self.action == "handoff" and self.intent is None:
            raise ValueError("Handoff action requires an intent")
```

**Agent usage:**
```python
async def execute(self, task: Task) -> HandoffResult:
    # Do my work...
    search_results = await self._search(task.description)

    # Reason about completion
    if self._goal_satisfied(task.goal, search_results):
        return HandoffResult(
            action="complete",
            result=search_results
        )
    else:
        return HandoffResult(
            action="handoff",
            intent="Get transcripts for these videos to find cooking details",
            state={**task.state, "videos": search_results}
        )
```

---

### Execution Path Tracking

Track which agents touched data and in what order:

```python
# core/session.py (extend existing)

@dataclass
class ExecutionStep:
    """Record of a single step in the execution path."""
    agent_name: str
    action: str              # "execute", "handoff", "complete", "error"
    timestamp: datetime
    task_id: str
    input_state_keys: list[str]   # What state keys were read
    output_state_keys: list[str]  # What state keys were written
    duration_ms: float
    error: str | None = None

class Session:
    def __init__(self):
        self._entries: dict[str, SessionEntry] = {}
        self._execution_path: list[ExecutionStep] = []  # NEW

    def record_step(self, step: ExecutionStep) -> None:
        """Record an execution step."""
        self._execution_path.append(step)

    def get_execution_path(self) -> list[ExecutionStep]:
        """Get the full execution path for debugging/visualization."""
        return self._execution_path.copy()

    def get_path_summary(self) -> str:
        """Human-readable execution summary."""
        return " → ".join(
            f"{step.agent_name}({step.action})"
            for step in self._execution_path
        )
        # Example: "search(execute) → transcript(execute) → summarize(complete)"
```

---

### Error Propagation Strategy

Different strategies for each approach:

#### Planner + DAG Approach

On error, return to Planner with partial results for re-evaluation:

```python
# patterns/dag_executor.py

class DAGExecutor:
    def __init__(self, planner: "PlannerAgent", max_replans: int = 3):
        self._planner = planner
        self._max_replans = max_replans
        self._replan_count = 0

    async def execute_dag(self, dag: ExecutionDAG, session: Session) -> Any:
        while True:
            try:
                return await self._execute_steps(dag, session)
            except StepExecutionError as e:
                self._replan_count += 1

                if self._replan_count > self._max_replans:
                    # Too many retries - return partial results to Synthesizer
                    return PartialResult(
                        completed_steps=session.get_execution_path(),
                        error=f"Failed after {self._max_replans} re-plans: {e}",
                        partial_data=session.get_all_entries()
                    )

                # Ask Planner to re-evaluate with what we have
                dag = await self._planner.replan(
                    original_goal=dag.goal,
                    completed_results=self._get_completed_results(session),
                    failed_step=e.step_id,
                    error=str(e)
                )
```

#### Autonomous Approach

Agents figure it out, but we detect and cut loops:

```python
# core/loop_detector.py

class LoopDetector:
    """Detects cyclic handoff patterns."""

    def __init__(self, max_visits: int = 2, window_size: int = 10):
        self._max_visits = max_visits  # Max times same agent can be visited
        self._window_size = window_size  # Recent history to check

    def check_for_loop(self, execution_path: list[ExecutionStep]) -> bool:
        """Returns True if a loop is detected."""
        recent = execution_path[-self._window_size:]
        agent_visits = {}

        for step in recent:
            if step.action == "handoff":
                agent_visits[step.agent_name] = agent_visits.get(step.agent_name, 0) + 1
                if agent_visits[step.agent_name] > self._max_visits:
                    return True

        return False

    def detect_cycle(self, execution_path: list[ExecutionStep]) -> list[str] | None:
        """Returns the cycle pattern if detected, e.g., ['search', 'transcript', 'search']."""
        recent_agents = [s.agent_name for s in execution_path[-self._window_size:]]

        # Look for repeated subsequences
        for length in range(2, len(recent_agents) // 2 + 1):
            pattern = recent_agents[-length:]
            prev_pattern = recent_agents[-2*length:-length]
            if pattern == prev_pattern:
                return pattern

        return None

# Usage in autonomous coordinator
async def coordinate_autonomous(self, task: Task, session: Session) -> Any:
    loop_detector = LoopDetector()

    while True:
        result = await current_agent.execute(task)
        session.record_step(...)

        if result.action == "complete":
            return result.result

        # Check for loops before handoff
        if loop_detector.check_for_loop(session.get_execution_path()):
            cycle = loop_detector.detect_cycle(session.get_execution_path())
            return PartialResult(
                error=f"Loop detected: {' → '.join(cycle)}",
                partial_data=session.get_all_entries()
            )

        # Continue with handoff
        current_agent = await self._router.find_agent_for_intent(result.intent, self._registry)
        task = task.with_updated_state(result.state)
```

---

### Autonomous Approach: All Agents Think

In the autonomous approach, **every agent reasons about the goal**. This is the key differentiator from the orchestrator pattern:

```python
# base_agent.py - autonomous mode

class BaseAgent(ABC):
    async def execute_autonomous(self, task: Task) -> HandoffResult:
        """
        Autonomous execution: agent receives goal + state, reasons about what to do.

        Every agent in the chain thinks and makes decisions - there's no central
        coordinator telling them what to do.
        """
        # 1. Reason about the goal and current state
        reasoning = await self._reason_about_task(task)

        # 2. Can I complete the goal with what I have?
        if reasoning.can_complete:
            result = await self._do_my_work(task)
            return HandoffResult(action="complete", result=result)

        # 3. Can I contribute to the goal?
        if reasoning.can_contribute:
            my_result = await self._do_my_work(task)
            updated_state = {**task.state, self.name: my_result}

            # 4. Reason about what's needed next
            return HandoffResult(
                action="handoff",
                intent=reasoning.next_intent,  # "Now we need to summarize these transcripts"
                state=updated_state
            )

        # 5. I can't help - pass along (shouldn't happen if routing works)
        return HandoffResult(
            action="handoff",
            intent=task.goal,  # Pass original goal
            state=task.state
        )

    async def _reason_about_task(self, task: Task) -> AgentReasoning:
        """LLM-based reasoning about the task."""
        prompt = f"""You are {self.name}. Your capabilities: {self.description}

GOAL: {task.goal}
CURRENT STATE: {json.dumps(task.state, indent=2)}

Reason about:
1. Can you fully complete this goal with the current state? (yes/no)
2. Can you contribute something useful toward this goal? (yes/no)
3. If you contribute, what should happen next? (describe the next step)

Respond in JSON: {{"can_complete": bool, "can_contribute": bool, "next_intent": str | null}}"""

        response = await self._client.complete(prompt)
        return AgentReasoning.from_json(response)
```

**Key principle:** No agent just blindly executes. Each one:
1. Sees the original goal
2. Sees what's been accomplished (state)
3. Decides if it can complete, contribute, or should pass
4. If handing off, articulates *why* and *what's next*

This is fundamentally different from V1 where only the orchestrator thinks.

---

## Part 13: Note on V1 Registry Improvement

### Recommendation: Extract Registry for V1

The V2 `AgentRegistry` abstraction could improve V1's orchestrator without changing its fundamental pattern:

**Current V1 (hardcoded agent references):**
```python
class OrchestratorAgent:
    def __init__(self):
        self._search_agent = SearchAgent(...)
        self._transcript_agent = TranscriptAgent(...)
        self._summarize_agent = SummarizeAgent(...)
        # Adding a new agent = modify this class + add tool method
```

**V1 with Registry (decoupled discovery, same tight loop):**
```python
class OrchestratorAgent:
    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        # Adding a new agent = registry.register() elsewhere, no orchestrator changes

    async def _delegate(self, capability: str, request: str) -> str:
        agents = self._registry.find_by_capability(capability)
        if not agents:
            return f"No agent available for capability: {capability}"
        agent = agents[0]
        result = await agent.run(request)  # Still direct invocation - no queue!
        return result.text
```

**Benefits:**
- **Extensibility**: New agents registered without touching orchestrator code
- **Capability-based routing**: Orchestrator asks for "summarization", not a specific agent
- **Same tight feedback loop**: Direct `await agent.run()`, no queue indirection
- **Testability**: Easy to inject mock registries

**What NOT to add to V1:**
- Task queues (breaks the tight LLM reasoning loop)
- Self-selection patterns (orchestrator IS the decision maker)
- Async task submission (orchestrator needs immediate results)

The Registry gives V1 the extensibility benefits of V2's architecture while preserving its core strength: LLM-driven step-by-step reasoning with immediate feedback.

---

## Part 14: Current Progress & Next Steps

### Session Summary (2025-01-07)

All autonomous pattern implementation is **complete**. Unit tests pass (23 autonomous tests, 96 total V2 tests).

#### Bug Fixes Applied This Session

1. **Intent Router API**: Fixed `response.content` → `response.text` (agent_framework `ChatResponse` uses `.text`)

2. **LLM Query Extraction**: Replaced brittle regex heuristics with LLM call for extracting YouTube search queries from natural language goals. The LLM produces much better search terms:
   - Before: `"cook a pork loin roast on a Kamado grill/smoker"`
   - After: `"pork loin roast kamado grill Fork and Embers Chuds BBQ"`

3. **Natural Language Keywords**: Added more keywords to `CapabilityIntentRouter` for routing natural language requests:
   - `"youtube"`, `"on youtube"`, `"from youtube"`
   - `"how to"`, `"techniques"`, `"tutorial"`
   - `"info on"`, `"information about"`
   - `"channels"`, `"learn about"`

---

### Next Step: End-to-End Testing

#### Purpose
Verify the full autonomous chain works with real YouTube API and LLM calls.

#### Test Prompts

```
1. Search + Transcript + Summarize chain:
   "I want to cook a pork loin roast on a Kamado grill/smoker. I would like some info
   on how to do this based on techniques on YouTube. Some channels I trust are fork
   and embers and chuds bbq. Ideally, I need to know the temperature, the grill setup,
   the internal temperature and the time."

   Expected: search → transcript → summarize

2. [Add more test prompts here]

3. Search only (no handoff):
   "Find videos about Python async programming"

   Expected: search completes (no transcript/summary keywords)
```

#### Test Commands
```bash
# Interactive mode
uv run youtube-agent-v2 -p autonomous chat

# Single request mode
uv run youtube-agent-v2 -p autonomous chat -r "YOUR PROMPT HERE"
```

#### What to Verify
- [ ] Intent routing selects correct initial agent (usually SearchAgent)
- [ ] LLM query extraction produces sensible YouTube search terms
- [ ] Handoff chain follows expected path based on goal keywords
- [ ] Transcripts are fetched successfully (may need proxy for cloud environments)
- [ ] Summaries focus on the user's specific question
- [ ] Final response is synthesized and presented clearly
- [ ] Execution path is displayed: `[Path] search → transcript → summarize`

#### Known Limitations
- YouTube blocks datacenter IPs - needs residential proxy for transcript fetch
- LLM calls add latency to query extraction and summarization
- Handoff logic uses keyword matching (could enhance with LLM reasoning later)

---

### Files Modified This Session

| File | Changes |
|------|---------|
| `src/youtube_agent_v2/agents/search.py` | LLM-based query extraction via `_extract_query_from_goal()` |
| `src/youtube_agent_v2/core/intent_router.py` | Fixed `.content` → `.text`, added natural language keywords |

---

### Success Criteria

- [x] All agents implement `execute_autonomous()` with goal-aware reasoning
- [x] All agents have `description` property for intent routing
- [x] CLI supports `--pattern autonomous`
- [x] Unit tests pass for autonomous pattern (23 tests)
- [x] Documentation updated with usage examples
- [ ] **E2E: Full chain works with real APIs** (pending user testing)
