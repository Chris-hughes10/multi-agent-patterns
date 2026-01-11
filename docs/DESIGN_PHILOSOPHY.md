# Design Philosophy

This document captures the architectural decisions and design philosophy behind the YouTube Agent codebase. It serves as a reference for the accompanying blog post and for contributors who want to understand *why* the code is structured this way.

---

## Core Principle: Clarity Over Cleverness

This codebase prioritizes **readability and teachability** over minimal line count. Every architectural decision should be explainable in one sentence. If a pattern requires a paragraph to justify, it's probably over-engineered.

---

## Layered Architecture

The codebase follows a layered architecture where each layer has a single, well-defined responsibility:

```
┌─────────────────────────────────────────────────────────┐
│                       cli/                              │
│              User-facing command interface              │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     agents/                             │
│         LLM personas with instructions + tools          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      tools/                             │
│          Thin wrappers exposing services to LLM         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    services/                            │
│              Business logic and domain rules            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     models/                             │
│               Data structures and DTOs                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      infra/                             │
│            Framework infrastructure (clients)           │
└─────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | One-Sentence Description | Contains |
|-------|-------------------------|----------|
| `cli/` | Parses user input and displays output | Argument parsing, status display, entry points |
| `agents/` | Defines LLM personas and their capabilities | Instructions, tool bindings, factory functions |
| `tools/` | Exposes services as LLM-callable functions | String-formatted wrappers, parameter validation |
| `services/` | Implements business logic | Classes with real functionality, domain rules |
| `models/` | Defines data structures | Pydantic models, dataclasses, DTOs |
| `infra/` | Provides framework plumbing | API clients, context providers, singletons |

### Why This Separation?

**1. Testability** - Each layer can be tested independently with appropriate mocking boundaries.

**2. Replaceability** - Swap YouTube for Vimeo? Replace `services/youtube.py`. Change storage from JSON to SQLite? Replace `services/storage.py`.

**3. Teachability** - New contributors can understand one layer at a time.

---

## Services vs Tools: The Key Distinction

This is the most important architectural decision to understand.

### Tools = LLM Interface

Tools are **thin wrappers** that make services callable by an LLM. They:

- Accept simple parameters (strings, numbers)
- Return formatted strings the LLM can reason about
- Handle parameter validation and error formatting
- Are stateless

```python
# tools/search.py
def search_youtube_formatted(query: str, max_results: int = 5) -> str:
    """What the LLM calls."""
    results = search_youtube(query, max_results)  # calls service
    return "\n".join(f"- {r.title} ({r.video_id})" for r in results)
```

### Services = Business Logic

Services contain the **real implementation**. They:

- Are reusable classes with configuration
- Return rich domain objects (models)
- Can be called from anywhere (CLI, tests, other services)
- May maintain state or connections

```python
# services/youtube.py
class YouTubeTranscriptFetcher:
    def __init__(self, proxy_url: str | None = None):
        self.proxy_url = proxy_url

    def fetch(self, video_id: str) -> Transcript:
        """Returns a rich Transcript object."""
        # Real implementation here
        ...
```

### The Flow

```
LLM decides to call "fetch_video_transcript"
    ↓
tools/transcript.py::fetch_video_transcript(video_id)
    ↓
services/youtube.py::YouTubeTranscriptFetcher.fetch(video_id)
    ↓
Returns Transcript object
    ↓
Tool formats as string for LLM
```

### Why Not Just Put Everything in Tools?

1. **Reusability** - Services can be called from CLI commands, tests, or scripts without going through the LLM interface.

2. **Testing** - Services return typed objects that are easy to assert against. Tools return formatted strings.

3. **Separation of concerns** - Tool code handles "how to present to LLM", service code handles "how to actually do it".

---

## Domain-Driven Organization

The `services/` package is organized by **domain**, not by technical function. This follows Domain-Driven Design (DDD) principles.

### What This Means

```
services/
├── youtube.py      # YouTube domain: search + transcript fetching
├── storage.py      # Persistence domain
└── summarizer.py   # Summarization domain
```

**Not** like this (functional organization):

```
services/
├── transcript_fetcher.py   # One function
├── search.py               # Another function
├── storage.py
└── summarizer.py
```

### Why Domain-Driven?

**Bounded Contexts** - In DDD, a "bounded context" is where a term has consistent meaning. "YouTube" is a bounded context:

- "video_id" means a YouTube video ID
- "channel" means a YouTube channel
- "transcript" means a YouTube transcript

Both search and transcript fetching operate within this context. Grouping them together:

1. **Cohesion** - Related code stays together
2. **Replaceability** - Swap YouTube for Vimeo by replacing one module
3. **Discoverability** - "Where's YouTube logic?" → `services/youtube.py`

### The Litmus Test

Ask: "If I replaced this external system, what would change?"

- Replace YouTube with Vimeo → `services/youtube.py` changes
- Replace JSON storage with SQLite → `services/storage.py` changes
- Replace Azure OpenAI with Anthropic → `services/summarizer.py` changes

Each domain boundary represents a potential replacement point.

---

## Testing Philosophy

We follow Kent Beck's pragmatic approach: **only mock external or long-running services**.

### The Mock Boundary

```
┌─────────────────────────────────────────────┐
│  agents/  →  tools/  →  services/           │  ← Test with REAL code
└─────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │ External APIs   │  ← MOCK here
                    │ - YouTube API   │
                    │ - Azure OpenAI  │
                    │ - Network I/O   │
                    └─────────────────┘
```

### What We Mock

| Always Mock | Never Mock |
|-------------|------------|
| YouTube transcript API calls | `TranscriptStorage` class |
| Azure OpenAI API calls | Service classes (mock their clients instead) |
| HTTP requests | Model transformations |
| System time (when testing timestamps) | Parsing and formatting logic |

### What We Don't Mock

- **Internal services** - `TranscriptStorage` is just JSON file I/O. It's fast, deterministic, and we control it. Test it for real.
- **Service classes** - Don't mock `TranscriptSummarizer`. Instead, inject a mock OpenAI client and test the real service logic.
- **Models and utilities** - These are pure functions with no external dependencies.

### Why This Approach?

**Higher confidence** - Tests exercise real code paths, catching integration bugs that pure unit tests miss.

**Less brittle** - Fewer mocks means fewer things to update when interfaces change.

**Faster feedback** - When something breaks, you know it's a real problem, not a mock configuration issue.

### Example

```python
# Good: Mock only the external API client
def test_summarizer_extracts_key_points():
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = fake_response(
        "Key points: 1. First point 2. Second point"
    )

    summarizer = TranscriptSummarizer(client=mock_client)  # Real service
    result = summarizer.summarize(real_transcript)         # Real logic

    assert "Key points" in result


# Good: Use real storage with temp directory
def test_storage_round_trip(tmp_path):
    storage = TranscriptStorage(storage_dir=tmp_path)  # Real service, temp dir
    storage.save(sample_transcript)

    loaded = storage.load("video123")
    assert loaded.transcript.full_text == sample_transcript.transcript.full_text
```

---

## Agent Design Principles

### Single Responsibility Per Agent

Each agent has ONE job:

| Agent | Responsibility | Does NOT Do |
|-------|---------------|-------------|
| SearchAgent | Find videos on YouTube | Fetch transcripts, summarize |
| TranscriptAgent | Fetch and store transcripts | Summarize, search |
| SummarizeAgent | Generate summaries | Fetch from YouTube |
| WriterAgent | Write files to disk | Any YouTube operations |

**Why?** Clear responsibilities make agents predictable and debuggable. When something goes wrong, you know which agent to investigate.

### Orchestrator Pattern

The OrchestratorAgent coordinates sub-agents but doesn't do real work itself:

```
User Request
    ↓
Orchestrator (decides what to do)
    ↓
    ├── "Need to search" → SearchAgent
    ├── "Need transcript" → TranscriptAgent
    ├── "Need summary" → SummarizeAgent
    └── "Need to save" → WriterAgent
```

The Orchestrator:
- Maintains conversation memory
- Knows what's been cached (via context injection)
- Delegates work to specialists
- Never calls YouTube or OpenAI directly

### Context Injection

The `TranscriptContextProvider` injects information about stored transcripts before each LLM call. This allows the Orchestrator to make intelligent decisions:

```
"You have 5 stored transcripts: video1 (summarized), video2 (not summarized)..."
```

Now the Orchestrator knows to use cached data instead of re-fetching.

---

## Configuration Philosophy

### Environment-Based Configuration

All configuration comes from environment variables (via pydantic-settings):

```python
class Settings(BaseSettings):
    azure_openai_endpoint: str
    azure_openai_deployment: str
    storage_dir: Path = Path("data/transcripts")
    proxy_url: str | None = None
```

**Why?**
- 12-factor app compliance
- Easy to override in different environments
- No secrets in code

### Runtime vs Static Configuration

| Type | Example | Where |
|------|---------|-------|
| Static | API endpoints, credentials | `Settings` (from env) |
| Runtime | Auto-save transcripts flag | `RuntimeConfig` (mutable) |

Runtime config can be changed per-session (e.g., `--no-store` flag).

---

## Error Handling Philosophy

### Custom Exceptions Per Domain

Each domain has its own exception types:

```python
# services/youtube.py
class YouTubeSearchError(Exception): ...
class TranscriptFetchError(Exception): ...

# services/summarizer.py
class SummarizationError(Exception): ...
```

**Why?**
- Callers can catch specific errors
- Error messages include domain context
- Easy to map to user-friendly messages in CLI

### Fail Fast, Recover Gracefully

- **Fail fast** on configuration errors (missing API key → immediate error)
- **Recover gracefully** on runtime errors (video unavailable → informative message, continue)

---

## Summary: Design Decisions at a Glance

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package organization | By layer (agents, tools, services) | Clear separation of concerns |
| Service organization | By domain (DDD) | Cohesion, replaceability |
| Tools vs Services | Thin tools, rich services | Reusability, testability |
| Mocking strategy | Mock external APIs only | Higher confidence tests |
| Agent design | Single responsibility | Predictability, debuggability |
| Configuration | Environment variables | 12-factor compliance |
| Error handling | Domain-specific exceptions | Clear error provenance |

---

## Applying These Patterns

When adding a new capability:

1. **Model first** - Define data structures in `models/`
2. **Service second** - Implement business logic in `services/`
3. **Tool third** - Create LLM-callable wrapper in `tools/`
4. **Agent last** - Add tool to appropriate agent or create new agent

When debugging:

1. **Check the layer** - Is it a tool formatting issue or a service logic issue?
2. **Check the domain** - Which bounded context owns this functionality?
3. **Check the mock boundary** - Is the test mocking too much or too little?
