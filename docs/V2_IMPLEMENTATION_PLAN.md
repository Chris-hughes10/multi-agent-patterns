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
| Phase 2: Blog Foundation | ⬜ Not started | |
| Phase 3: V2 Core Abstractions | ⬜ Not started | |
| Phase 4: V2 Agents | ⬜ Not started | |
| Phase 5: V2 Dispatcher Pattern | ⬜ Not started | |
| Phase 6: V2 Self-Selection Pattern | ⬜ Not started | |
| Phase 7: Final Documentation | ⬜ Not started | |

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
