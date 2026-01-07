# Understanding Python's Event Loop in Multi-Agent Systems

This document explains how Python's `asyncio` event loop enables parallel execution in multi-agent architectures, using our YouTube Agent V1 orchestrator as a concrete example.

---

## Table of Contents

1. [The Problem: Sequential vs Parallel Execution](#the-problem-sequential-vs-parallel-execution)
2. [Python's Event Loop: The Basics](#pythons-event-loop-the-basics)
3. [V1 Orchestrator Architecture](#v1-orchestrator-architecture)
4. [Making Tools Async: Three Patterns](#making-tools-async-three-patterns)
5. [How Parallel Execution Actually Works](#how-parallel-execution-actually-works)
6. [The Framework's Role](#the-frameworks-role)
7. [Common Pitfalls](#common-pitfalls)
8. [Key Takeaways](#key-takeaways)

---

## The Problem: Sequential vs Parallel Execution

Consider an orchestrator that needs to call three sub-agents:

```python
# Sequential execution (blocking)
result1 = search_agent.run("find videos")      # 100ms
result2 = transcript_agent.run("get transcript") # 100ms
result3 = summarize_agent.run("summarize")      # 100ms
# Total: 300ms
```

Each call blocks until complete. Even if these operations are independent, they execute one after another.

**The goal**: Execute independent operations concurrently so they overlap:

```
Timeline (sequential):
|--search--|--transcript--|--summarize--|  = 300ms

Timeline (parallel):
|--search-----|
|--transcript-|
|--summarize--|  = 100ms (limited by slowest)
```

---

## Python's Event Loop: The Basics

### What is an Event Loop?

An event loop is a programming pattern that waits for events (I/O completion, timers, etc.) and dispatches them to handlers. Python's `asyncio` provides this pattern for concurrent I/O operations.

```python
import asyncio

async def fetch_data():
    await asyncio.sleep(1)  # Non-blocking wait
    return "data"

# The event loop manages this coroutine
asyncio.run(fetch_data())
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Coroutine** | A function defined with `async def`. Returns a coroutine object when called. |
| **Awaitable** | Something you can `await` - coroutines, Tasks, Futures |
| **Task** | A wrapped coroutine scheduled for execution |
| **Event Loop** | The scheduler that runs Tasks and handles I/O callbacks |

### The Critical Insight: `await` is a Yield Point

When you `await` something, you're saying "pause this coroutine and let others run until this I/O completes":

```python
async def example():
    print("Start")
    await asyncio.sleep(1)  # <-- Coroutine yields here
    print("End")            #     Other coroutines can run while waiting
```

**Without `await`**, the code blocks and no other coroutine can run.

---

## V1 Orchestrator Architecture

### Request Flow

```
User Request
    │
    ▼
CLI (sync) ──► asyncio.run()
    │
    ▼
OrchestratorAgent.run() [async]
    │
    ▼
ChatAgent ──► LLM decides which sub-agent(s) to call
    │
    ▼
Tool calls: ask_search_agent(), ask_transcript_agent(), etc.
    │
    ▼
Sub-agents execute [async] ──► return results
    │
    ▼
Orchestrator LLM synthesizes response
    │
    ▼
Response to user
```

### The Orchestrator Class

From `src/youtube_agent/agents/orchestrator.py`:

```python
class OrchestratorAgent:
    """Orchestrator that coordinates sub-agents for YouTube research."""

    async def run(self, user_request: str) -> str:
        """Run the orchestrator with a user request."""
        orchestrator = self.get_orchestrator()
        result = await orchestrator.run(user_request, thread=self._thread)
        return result.text
```

### Sub-Agent Delegation

The key to parallel execution is how we delegate to sub-agents. From the actual implementation:

```python
async def _delegate(self, agent_name: str, request: str) -> str:
    """Delegate a request to a sub-agent.

    :param agent_name: Name of the agent to delegate to
    :param request: The request to send to the agent
    :return: The agent's response
    """
    logger.debug("%sAgent called with: %s", agent_name.title(), request)
    agent = self._get_agent(agent_name)
    result = await agent.run(request)
    logger.debug(
        "%sAgent response: %s",
        agent_name.title(),
        result.text[:200] if result.text else "empty",
    )
    return result.text
```

Each tool wrapper is also async:

```python
async def ask_search_agent(
    self,
    request: Annotated[str, Field(description="Request for the Search Agent")],
) -> str:
    """Delegate a search request to the Search Agent."""
    return await self._delegate("search", request)

async def ask_transcript_agent(
    self,
    request: Annotated[str, Field(description="Request for the Transcript Agent")],
) -> str:
    """Delegate a transcript request to the Transcript Agent."""
    return await self._delegate("transcript", request)
```

**Key point**: These are `async def` functions that `await` the sub-agent. This allows the event loop to run multiple delegations concurrently.

---

## Making Tools Async: Three Patterns

Not all code is natively async. Here's how we handle different scenarios in our codebase:

### Pattern 1: Native Async Libraries

For libraries with async support, use them directly. From `src/youtube_agent/services/youtube.py`:

```python
import httpx

async def search_youtube(query: str, max_results: int = 5) -> list[VideoSearchResult]:
    """Search YouTube for videos matching the query.

    This is an async function that uses httpx for non-blocking HTTP requests.
    """
    if not query or not query.strip():
        raise YouTubeSearchError(query, "Query cannot be empty")

    try:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 ...",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            html = response.text

        # Extract videos from HTML
        video_data = _extract_videos_from_html(html, max_results)
        return [VideoSearchResult(**v) for v in video_data]

    except Exception as e:
        raise YouTubeSearchError(query, str(e)) from e
```

**Characteristics**:
- Zero thread overhead
- True non-blocking I/O
- Best performance

**When to use**: HTTP calls (`httpx`, `aiohttp`), databases (`asyncpg`, `motor`), LLM clients (`AsyncAzureOpenAI`)

### Pattern 2: Thread Wrapper for Sync Libraries

Some libraries don't support async. Wrap them with `asyncio.to_thread()`. From `src/youtube_agent/services/youtube.py`:

```python
def _fetch_transcript_sync(
    url_or_id: str,
    languages: list[str] | None = None,
    fetcher: TranscriptFetcher | None = None,
) -> TranscriptResult:
    """Synchronous implementation of transcript fetching.

    This is the internal sync version. Use fetch_transcript() for the async API.
    """
    video_id = extract_video_id(url_or_id)

    if fetcher is None:
        settings = get_settings()
        fetcher = YouTubeTranscriptFetcher(proxy_url=settings.proxy_url)

    transcript = fetcher.fetch(video_id, languages)
    metadata = VideoMetadata(video_id=video_id)

    return TranscriptResult(metadata=metadata, transcript=transcript)


async def fetch_transcript(
    url_or_id: str,
    languages: list[str] | None = None,
    fetcher: TranscriptFetcher | None = None,
) -> TranscriptResult:
    """Fetch a transcript from YouTube - main entry point.

    Uses asyncio.to_thread() to run the sync youtube-transcript-api
    in a thread pool, avoiding blocking the event loop.
    """
    return await asyncio.to_thread(_fetch_transcript_sync, url_or_id, languages, fetcher)
```

**How it works**:
1. `asyncio.to_thread()` submits the sync function to a thread pool
2. The calling coroutine yields (other coroutines can run)
3. When the thread completes, the coroutine resumes

**Characteristics**:
- Thread pool overhead (but minimal)
- Sync code runs in background thread
- Event loop stays responsive

**When to use**: Sync-only third-party libraries (like `youtube_transcript_api`), file I/O, CPU-bound tasks

### Pattern 3: Async LLM Clients

For Azure OpenAI, use the async client. From `src/youtube_agent/services/summarizer.py`:

```python
from openai import AsyncAzureOpenAI

class TranscriptSummarizer:
    """Summarizes YouTube transcripts using Azure OpenAI.

    All methods are async to avoid blocking the event loop.
    """

    def _create_client(self) -> AsyncAzureOpenAI:
        """Create an async Azure OpenAI client from settings."""
        if self._settings.use_azure_ad:
            credential = AzureCliCredential(**credential_kwargs)
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            return AsyncAzureOpenAI(
                api_version=self._settings.azure_openai_api_version,
                azure_endpoint=self._settings.azure_openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        return AsyncAzureOpenAI(
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
            azure_endpoint=self._settings.azure_openai_endpoint,
        )

    async def summarize(
        self,
        transcript_text: str,
        video_title: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Summarize a transcript."""
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise SummarizationError(str(e)) from e
```

### Pattern 4: File I/O with Thread Wrapper

For file operations, wrap with `asyncio.to_thread()`. From `src/youtube_agent/tools/writer.py`:

```python
def _write_markdown_sync(content: str, filename: str, output_dir: str) -> str:
    """Synchronous implementation of markdown file writing."""
    if not filename.endswith(".md"):
        filename = f"{filename}.md"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / filename
    file_path.write_text(content, encoding="utf-8")

    return f"Successfully wrote {len(content)} characters to {file_path}"


async def write_markdown_file(
    content: Annotated[str, Field(description="Markdown content to write")],
    filename: Annotated[str, Field(description="Output filename")],
    output_dir: Annotated[str, Field(description="Output directory")] = "output",
) -> str:
    """Write markdown content to a file."""
    try:
        return await asyncio.to_thread(_write_markdown_sync, content, filename, output_dir)
    except Exception as e:
        return f"Error writing file: {e}"
```

### Summary Table: Our Implementation

| Component | File | Pattern | Implementation |
|-----------|------|---------|----------------|
| YouTube search | `services/youtube.py` | Native async | `httpx.AsyncClient` |
| Transcript fetching | `services/youtube.py` | Thread wrapper | `asyncio.to_thread()` |
| LLM summarization | `services/summarizer.py` | Native async | `AsyncAzureOpenAI` |
| Storage operations | `tools/transcript.py` | Thread wrapper | `asyncio.to_thread(storage.load)` |
| Markdown writing | `tools/writer.py` | Thread wrapper | `asyncio.to_thread()` |
| Orchestrator tools | `agents/orchestrator.py` | Native async | `async def` + `await agent.run()` |

---

## How Parallel Execution Actually Works

### The Magic: `asyncio.gather()`

When the LLM decides to call multiple tools, the framework can execute them in parallel:

```python
async def execute_tools(tool_calls: list[ToolCall]) -> list[str]:
    """Execute multiple tool calls in parallel."""
    coroutines = [execute_single_tool(tc) for tc in tool_calls]
    results = await asyncio.gather(*coroutines)
    return results
```

### Step-by-Step Execution

```python
# LLM returns: "Call ask_search_agent AND ask_transcript_agent"

# Framework creates coroutines (not yet running):
coro1 = ask_search_agent("find videos about RAG")
coro2 = ask_transcript_agent("get transcript for abc123")

# gather() schedules both as Tasks:
results = await asyncio.gather(coro1, coro2)

# Timeline:
# t=0ms:   Both coroutines start
# t=0ms:   coro1 sends HTTP request via httpx, yields
# t=0ms:   coro2 starts thread for transcript via to_thread(), yields
# t=50ms:  coro2's thread completes, resumes
# t=100ms: coro1's HTTP response arrives, resumes
# t=100ms: Both results ready, gather() returns
```

### Visualizing the Event Loop

```
Event Loop Timeline
===================

     |---- coro1: search agent ----|
     |                              |
     |  await httpx.get()           | <-- yields, waiting for HTTP
     |  .........................   |
     |                         +--> | response arrives, resumes
     |                              |
     |---- coro2: transcript -------|
     |                              |
     |  await to_thread(fetch)      | <-- yields, thread running
     |  ................            |
     |             +--> resume      | thread done
     |                              |
=====|==============================|=====
   t=0                           t=100ms

Both complete in ~100ms instead of 200ms!
```

### Proof: Our Test

From `tests/test_async_parallel.py`:

```python
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

        from youtube_agent.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent()
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
        assert elapsed < 0.25, f"Took {elapsed:.3f}s - calls may not be running in parallel!"
        print(f"\n✓ 3 parallel calls completed in {elapsed:.3f}s (expected ~0.1s)")
```

---

## The Framework's Role

### How the Agent Framework Supports Async

The agent framework (Microsoft Agent Framework in our case) detects async tools automatically using `inspect.isawaitable()`:

```python
# Inside the framework (simplified):
import inspect

async def execute_tool(tool_func, args):
    result = tool_func(**args)

    # Check if the tool returned a coroutine
    if inspect.isawaitable(result):
        return await result  # Async tool - await it
    return result  # Sync tool - return directly
```

This means you can mix sync and async tools:

```python
tools = [
    sync_tool,        # Regular function
    async_tool,       # async def function
]
```

The framework handles both correctly.

### Why This Matters

You don't need to rewrite everything at once. Migrate tools to async incrementally:

1. Start with sync tools (they work)
2. Convert hot paths to async (search, LLM calls)
3. Wrap remaining sync code with `to_thread()`
4. Framework handles the mix seamlessly

---

## Common Pitfalls

### Pitfall 1: Blocking in Async Code

```python
# BAD - blocks the event loop!
async def bad_fetch():
    import urllib.request
    response = urllib.request.urlopen(url)  # BLOCKING!
    return response.read()

# GOOD - use async HTTP client
async def good_fetch():
    async with httpx.AsyncClient() as client:
        response = await client.get(url)  # Non-blocking
        return response.text
```

**Rule**: Never use blocking I/O in async functions without `to_thread()`.

### Pitfall 2: Forgetting to Await

```python
# BAD - coroutine never executes!
async def process():
    fetch_data()  # Returns coroutine object, doesn't run it

# GOOD
async def process():
    await fetch_data()  # Actually runs the coroutine
```

Python will warn: `RuntimeWarning: coroutine 'fetch_data' was never awaited`

### Pitfall 3: Creating Event Loop Inside Event Loop

```python
# BAD - crashes with "This event loop is already running"
async def outer():
    asyncio.run(inner())  # Can't nest asyncio.run()!

# GOOD - just await it
async def outer():
    await inner()
```

### Pitfall 4: Thread Safety with Shared State

```python
# DANGEROUS - async code can interleave!
counter = 0

async def increment():
    global counter
    temp = counter      # <-- could yield here
    await some_io()     # <-- another coroutine runs
    counter = temp + 1  # <-- race condition!

# SAFE - use async lock
lock = asyncio.Lock()

async def safe_increment():
    async with lock:
        global counter
        counter += 1
```

---

## Key Takeaways

### 1. `async/await` Enables Concurrency, Not Parallelism

- **Concurrency**: Multiple tasks in progress (interleaved)
- **Parallelism**: Multiple tasks executing simultaneously (threads/processes)

`asyncio` provides concurrency for I/O-bound work. The event loop runs one piece of Python code at a time, but I/O operations happen in the background.

### 2. The Three Async Patterns

| Scenario | Solution |
|----------|----------|
| Library has async support | Use it directly (`httpx`, `AsyncAzureOpenAI`) |
| Library is sync-only | Wrap with `asyncio.to_thread()` |
| CPU-bound work | Use `ProcessPoolExecutor` or move to a worker |

### 3. Benefits for Multi-Agent Systems

- **Latency reduction**: Parallel tool calls complete faster
- **Resource efficiency**: Single thread handles many I/O operations
- **Responsiveness**: Long operations don't block the system
- **Scalability**: Handle more concurrent requests

### 4. Our Migration Path

1. Made orchestrator `_delegate()` async
2. Made all `ask_*_agent()` tool wrappers async
3. Converted `search_youtube()` to use `httpx.AsyncClient`
4. Converted `TranscriptSummarizer` to use `AsyncAzureOpenAI`
5. Wrapped sync `youtube_transcript_api` with `asyncio.to_thread()`
6. Wrapped all file I/O operations with `asyncio.to_thread()`
7. Added tests proving parallel execution

### 5. Testing Async Code

```python
import pytest
import asyncio
import time

@pytest.mark.asyncio
async def test_parallel_execution():
    """Prove that 3 async calls run in parallel."""

    async def slow_task():
        await asyncio.sleep(0.1)  # 100ms
        return "done"

    start = time.perf_counter()
    results = await asyncio.gather(
        slow_task(),
        slow_task(),
        slow_task(),
    )
    elapsed = time.perf_counter() - start

    assert len(results) == 3
    assert elapsed < 0.15  # Should be ~100ms, not 300ms
```

---

## Further Reading

- [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html)
- [Real Python: Async IO in Python](https://realpython.com/async-io-python/)
- [httpx documentation](https://www.python-httpx.org/)
- [Azure OpenAI Async Client](https://learn.microsoft.com/en-us/python/api/azure-ai-openai/)

---

## Appendix: Quick Reference

### Starting an Event Loop

```python
# From sync code (entry point)
asyncio.run(main())

# From async code
await some_coroutine()
```

### Running Tasks in Parallel

```python
# Wait for all to complete
results = await asyncio.gather(coro1(), coro2(), coro3())

# First to complete wins
done, pending = await asyncio.wait(
    [coro1(), coro2()],
    return_when=asyncio.FIRST_COMPLETED
)
```

### Wrapping Sync Code

```python
# Run sync function in thread pool
result = await asyncio.to_thread(sync_function, arg1, arg2)

# Custom executor
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(executor, sync_function, arg1)
```

### Timeouts

```python
try:
    result = await asyncio.wait_for(slow_coro(), timeout=5.0)
except asyncio.TimeoutError:
    print("Operation timed out")
```
