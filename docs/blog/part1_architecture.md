# Architecting Multi-Agent Systems: Lessons from Building a YouTube Research Assistant

The AI agent landscape is crowded. LangChain, CrewAI, AutoGen, the Claude Agent SDK - new frameworks appear constantly, each promising to simplify building intelligent applications. Yet most tutorials focus on "hello world" demos: a single agent answering questions, maybe calling a tool or two.

I wanted to go beyond that. Not to build something enterprise-scale, but to build something **non-trivial yet clean** - proving that agent systems can be architected with the same discipline we apply to any serious software project.

## The Problem That Started This

I'm a BBQ enthusiast, and YouTube is an incredible resource for learning. Channels like Chuds BBQ, Meat Church, and Mad Scientist BBQ have content that rivals any cookbook - but the knowledge is locked in video format. When I'm planning a cook, I find myself:

1. Searching across multiple channels for a specific technique
2. Watching (or skipping through) several videos
3. Cross-referencing temperatures, times, and methods
4. Manually aggregating notes into something I can reference at the grill

This felt like a good candidate for automation. Search YouTube, fetch transcripts, extract the relevant information, synthesise it into a reference document. Four distinct capabilities, potentially handled by specialized agents.

But more importantly, it felt like a good test case for a question I had: **can you build a multi-agent system that doesn't become an unmaintainable mess?**

Most agent code I've seen mixes everything together - LLM calls, API integrations, business logic, formatting - in ways that would make any software engineer wince. I wanted to prove that the patterns we use for clean architecture in traditional systems apply equally to agent systems.

## In this article, we shall cover:

- Why agent systems benefit from the same layered architecture as any complex application
- The critical distinction between **tools** (LLM interface) and **services** (business logic) - the key insight that unlocks clean agent design
- How Domain-Driven Design concepts map naturally to agent architectures
- A practical example: four specialized agents with clear boundaries

The specific framework matters less than the principles. What follows applies whether you're using the Claude Agent SDK, LangChain, or building your own orchestration.

Let's start with the problem.

---

## The Architecture Challenge

Agent code gets messy fast. Here's what our first attempt looked like:

```python
# orchestrator.py - the "everything file"

def search_and_summarize(query: str) -> str:
    # Search YouTube
    response = requests.get(f"https://youtube.com/results?q={query}")
    videos = parse_html_for_videos(response.text)

    # Fetch transcripts
    transcripts = []
    for video in videos[:3]:
        transcript = YouTubeTranscriptApi.get_transcript(video.id)
        transcripts.append(transcript)

    # Call LLM to summarize
    client = AzureOpenAI(...)
    summary = client.chat.completions.create(
        messages=[{"role": "user", "content": f"Summarize: {transcripts}"}]
    )

    # Save to file
    with open("output.md", "w") as f:
        f.write(summary)

    return summary
```

This works for a demo. But it's untestable without hitting real APIs, impossible to reuse components, and will become incomprehensible as we add features.

The core insight that changed our architecture: **LLM-callable functions have fundamentally different concerns than business logic**. Separating them unlocks testability and reusability.

### The Layered Architecture

We settled on six layers, each with a single, well-defined responsibility. If you're familiar with Domain-Driven Design, you'll recognise the structure:

```
┌─────────────────────────────────────────────────────────┐
│                   application/                          │
│              User-facing command interface              │
│                                                         │
│                   [Presentation Layer]                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     agents/                             │
│         LLM personas with instructions + tools          │
│                                                         │
│                   [Application Layer]                   │
│            Orchestrates domain operations               │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      tools/                             │
│          Thin wrappers exposing services to LLM         │
│                                                         │
│             [Anti-Corruption Layer / Adapters]          │
│         Translates between LLM and domain language      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    services/                            │
│              Business logic and domain rules            │
│                                                         │
│                    [Domain Layer]                       │
│              The heart of your application              │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     models/                             │
│               Data structures and DTOs                  │
│                                                         │
│               [Domain Model / Entities]                 │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      infra/                             │
│            Framework infrastructure (clients)           │
│                                                         │
│                 [Infrastructure Layer]                  │
│            External systems, persistence, APIs          │
└─────────────────────────────────────────────────────────┘
```

The DDD mapping isn't forced - it emerges naturally because agent systems have the same concerns as any complex application:

| Layer | DDD Concept | Agent System Role |
|-------|-------------|-------------------|
| `application/` | Presentation | User interaction, output formatting |
| `agents/` | Application | Orchestrates workflows, coordinates domain operations |
| `tools/` | Anti-Corruption Layer | Translates between LLM interface and domain language |
| `services/` | Domain | Core business logic, domain rules, the "what" |
| `models/` | Domain Model | Entities, value objects, domain concepts |
| `infra/` | Infrastructure | External APIs, persistence, framework plumbing |

The `tools/` layer as an Anti-Corruption Layer is particularly interesting. In DDD, an ACL protects your domain model from external system concepts. Here, it protects your domain from the LLM's interface requirements - translating between "strings the LLM can reason about" and "rich domain objects your code works with".

The flow is strictly downward. Agents use tools. Tools call services. Services work with models. This constraint forces clear thinking about where code belongs.

---

## Tools vs Services: The Key Distinction

This is the most important architectural decision to understand.

When an LLM "calls a tool", it's really doing two things: **invoking a function** and **interpreting the result**. The function needs to accept simple parameters (strings, numbers) and return text the LLM can reason about. That's it.

But the actual work - searching YouTube, parsing HTML, handling errors - is complex. It involves configuration, error handling, and returns rich objects with multiple fields.

We split these concerns:

### Tools = LLM Interface

Tools are thin wrappers. They:

- Accept simple parameters (strings, numbers, booleans)
- Call the appropriate service
- Format the result as a string the LLM can understand
- Are stateless

```python
# tools/transcript.py

async def fetch_video_transcript(
    video_id: Annotated[str, Field(description="YouTube video ID")]
) -> str:
    """Fetch the transcript for a YouTube video.

    Returns the full transcript text with video metadata.
    """
    result = await fetch_transcript(video_id)  # calls service

    return f"""## {result.metadata.title}
Channel: {result.metadata.channel}
Duration: {result.metadata.duration}

### Transcript
{result.transcript.full_text}
"""
```

Notice what the tool does NOT do:
- No configuration management
- No error handling beyond basic formatting
- No complex return types
- No business logic

### Services = Business Logic

Services contain the real implementation. They:

- Are reusable classes with configuration
- Return rich domain objects (models)
- Can be called from anywhere (CLI, tests, other services)
- May maintain state or connections

```python
# services/youtube.py

class YouTubeTranscriptFetcher:
    """Fetches transcripts from YouTube videos."""

    def __init__(self, proxy_url: str | None = None):
        self.proxy_url = proxy_url

    async def fetch(
        self,
        video_id: str,
        languages: list[str] | None = None
    ) -> TranscriptResult:
        """Fetch transcript with full metadata.

        Returns a TranscriptResult containing the transcript text,
        video metadata, and language information.
        """
        # Real implementation with error handling, retries, etc.
        raw_transcript = await self._fetch_from_api(video_id, languages)
        metadata = await self._fetch_metadata(video_id)

        return TranscriptResult(
            metadata=metadata,
            transcript=Transcript(
                full_text=self._format_transcript(raw_transcript),
                segments=raw_transcript,
                language=self._detect_language(raw_transcript),
            ),
        )
```

### The Flow

When the LLM decides to fetch a transcript:

```
LLM decides to call "fetch_video_transcript"
    ↓
tools/transcript.py::fetch_video_transcript(video_id)
    ↓
services/youtube.py::YouTubeTranscriptFetcher.fetch(video_id)
    ↓
Returns TranscriptResult object
    ↓
Tool formats as string for LLM
```

### Why This Matters

**1. Reusability** - Services can be called from the CLI directly, from tests, or from scripts, without going through the LLM:

```python
# CLI command that bypasses the agent entirely
@click.command()
def download_transcript(video_id: str, output: str):
    fetcher = YouTubeTranscriptFetcher()
    result = fetcher.fetch(video_id)
    Path(output).write_text(result.transcript.full_text)
```

**2. Testability** - Services return typed objects that are easy to assert against. Tools return formatted strings which are harder to validate:

```python
# Testing a service - clear assertions
def test_fetcher_returns_transcript():
    result = fetcher.fetch("abc123")
    assert result.transcript.full_text
    assert result.metadata.video_id == "abc123"
    assert result.transcript.language in ["en", "en-US"]

# Testing a tool - string parsing required
def test_tool_formats_correctly():
    output = fetch_video_transcript("abc123")
    assert "## " in output  # Has title?
    assert "Transcript" in output  # Has section header?
    # Much harder to validate structure
```

**3. Separation of Concerns** - Tool code handles "how to present to LLM", service code handles "how to actually do it". When YouTube's API changes, only `services/youtube.py` needs updating. When we want different output formatting, only the tool changes.

---

## Domain-Driven Organisation

With the tools/services split established, the next question is: how should we organise the `services/` package - our Domain Layer?

This is where another DDD concept becomes directly applicable: **Bounded Contexts**.

We had two options:

**Option A: By Function**
```
services/
├── search.py           # YouTube search
├── transcript.py       # Transcript fetching
├── summarizer.py       # AI summarization
└── storage.py          # Persistence
```

**Option B: By Bounded Context**
```
services/
├── youtube.py          # Search + transcripts (same context)
├── summarizer.py       # AI summarization
└── storage.py          # Persistence
```

We chose Option B. Here's why.

### Bounded Contexts

In Domain-Driven Design, a bounded context is a boundary within which a term has consistent meaning. "YouTube" is a bounded context:

- "video_id" means a YouTube video ID
- "channel" means a YouTube channel
- "transcript" means a YouTube transcript

Both search and transcript fetching operate within this context. They share:
- The same API surface (YouTube)
- The same domain concepts (videos, channels)
- The same error conditions (rate limits, unavailable videos)

Grouping them together provides:

**Cohesion** - Related code stays together. When debugging transcript issues, you don't need to check multiple files.

**Replaceability** - Want to add Vimeo support? Create `services/vimeo.py` with the same interface. The rest of the system doesn't change.

**Discoverability** - "Where's YouTube logic?" → `services/youtube.py`. Simple.

### The Litmus Test

When deciding where code belongs, ask: "If I replaced this external system, what would change?"

| Change | Files Affected |
|--------|----------------|
| Replace YouTube with Vimeo | `services/youtube.py` → `services/vimeo.py` |
| Replace JSON storage with SQLite | `services/storage.py` |
| Replace Azure OpenAI with Anthropic | `services/summarizer.py` |

Each domain boundary represents a potential replacement point. If multiple files would need to change for a single external system swap, your boundaries might be wrong.

---

## Agent Design: Single Responsibility

With our layer structure and domain organisation in place, let's look at the agents themselves.

Each agent has exactly one job:

| Agent | Responsibility | Does NOT |
|-------|---------------|----------|
| **SearchAgent** | Find videos on YouTube | Fetch transcripts, summarize |
| **TranscriptAgent** | Fetch and store transcripts | Summarize, search |
| **SummarizeAgent** | Generate summaries | Fetch from YouTube |
| **WriterAgent** | Write files to disk | Any YouTube operations |

This might seem overly restrictive. Why not let the TranscriptAgent also summarize, since it already has the transcript text?

The answer is predictability and debuggability. When something goes wrong:
- If summaries are bad, check SummarizeAgent
- If transcripts are missing, check TranscriptAgent
- If search results are irrelevant, check SearchAgent

Mixed responsibilities make debugging harder. "Is it a search problem or a transcript problem?" becomes a common question when agents do multiple things.

### The Orchestrator Pattern

With four single-responsibility agents, we need coordination. The OrchestratorAgent handles this:

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

The orchestrator:
- Maintains conversation memory
- Knows what's been cached (via context injection)
- Delegates work to specialists
- Never calls YouTube or OpenAI directly

This separation means we can test each specialist agent independently, with clear inputs and outputs.

### What an Agent Looks Like

An agent definition is surprisingly simple. Here's the SearchAgent:

```python
class SearchAgent:
    """Agent specialized for YouTube video search."""

    def get_agent(self) -> ChatAgent:
        return ChatAgent(
            name="SearchAgent",
            instructions="""You are a YouTube Search Agent.
            Your job is to find relevant YouTube videos based on user queries.
            Use the search_youtube tool to find videos.
            You ONLY search - you do not fetch transcripts or summarize.""",
            tools=[search_youtube_formatted],  # Tool from tools/ layer
        )
```

Notice the pattern:
- **Instructions** define the agent's persona and boundaries
- **Tools** are functions from the `tools/` layer (which call services)
- The agent doesn't know about YouTube APIs - it just calls tools

### What the Orchestrator Looks Like

The orchestrator follows the same pattern, but its tools delegate to other agents:

```python
class OrchestratorAgent:
    """Coordinates sub-agents for YouTube research tasks."""

    def get_orchestrator(self) -> ChatAgent:
        return ChatAgent(
            name="Orchestrator",
            instructions="""You coordinate YouTube research tasks.
            You have access to specialist agents - delegate to them.
            Never try to search YouTube or fetch transcripts yourself.""",
            tools=[
                self.ask_search_agent,
                self.ask_transcript_agent,
                self.ask_summarize_agent,
                self.ask_writer_agent,
            ],
        )

    async def ask_search_agent(self, request: str) -> str:
        """Delegate a search request to the Search Agent."""
        agent = SearchAgent().get_agent()
        result = await agent.run(request)
        return result.text

    async def ask_transcript_agent(self, request: str) -> str:
        """Delegate a transcript request to the Transcript Agent."""
        agent = TranscriptAgent().get_agent()
        result = await agent.run(request)
        return result.text

    # ... similar for summarize and writer
```

The orchestrator's "tools" are delegation functions. When the LLM decides to search, it calls `ask_search_agent`, which runs the SearchAgent and returns its result. The orchestrator sees the result and decides what to do next.

This is the hub-and-spoke pattern:

```
                    ┌─────────────┐
                    │ Orchestrator│
                    │   (LLM)     │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │ Search  │      │Transcript│     │Summarize│
    │  Agent  │      │  Agent  │      │  Agent  │
    └─────────┘      └─────────┘      └─────────┘
```

Every interaction flows through the center. The orchestrator accumulates context from each step, maintaining the full conversation history.

### Context Injection

One subtle but important pattern: the orchestrator needs to know what transcripts are already cached to make smart decisions. We use a `TranscriptContextProvider` that injects this information before each LLM call:

```python
class TranscriptContextProvider:
    """Provides context about stored transcripts to the orchestrator."""

    def get_context(self) -> str:
        stored = self.storage.list_transcripts()
        if not stored:
            return "No transcripts currently stored."

        lines = ["You have these transcripts available:"]
        for t in stored:
            status = "summarized" if t.has_summary else "not summarized"
            lines.append(f"- {t.title} ({t.video_id}): {status}")

        return "\n".join(lines)
```

Now the orchestrator can reason: "The user wants a summary, and I already have the transcript cached, so I'll skip fetching and go straight to SummarizeAgent."

---

## A Note on Testing

A natural benefit of the layered architecture is testability. With clear boundaries between layers, testing strategy becomes straightforward.

The principle we follow: **mock at the system boundary, not internally**.

```
┌─────────────────────────────────────────────┐
│  agents/  →  tools/  →  services/           │  ← Test with REAL code
└─────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │ External APIs   │  ← MOCK here
                    │ - YouTube API   │
                    │ - Azure OpenAI  │
                    └─────────────────┘
```

Don't mock your own services. If you're testing `TranscriptSummarizer`, inject a mock OpenAI client - but let the real service logic execute. If you're testing storage, use a temp directory - but exercise the real file I/O.

This gives higher confidence (real code paths), less brittle tests (fewer mocks to maintain), and catches the integration bugs that slip through pure unit tests.

---

## Key Takeaways

These principles apply regardless of which agent framework you choose:

1. **Layer your architecture** - Presentation, Application, Domain, Infrastructure. Agent systems have the same concerns as any complex application.

2. **Separate tools from services** - Tools are the Anti-Corruption Layer between LLMs and your domain. Keep them thin. Let services do the real work.

3. **Organise by bounded context** - Group code by the external system or domain concept, not by function. When you need to replace YouTube with Vimeo, one file changes.

4. **Single responsibility for agents** - Each agent does one thing well. Coordination happens in a dedicated orchestrator (for now - we'll revisit this in Part 2).

---

## View the Code

All patterns described here are implemented in the reference codebase:

- **[V1 Orchestrator Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_agent_orchestrator)** - The architecture explored in this post
- **[Full Source Code](https://github.com/Chris-hughes10/agents-explore)** - Complete implementation with tests
- **[Documentation](https://github.com/Chris-hughes10/agents-explore/tree/main/docs)** - Design philosophy, patterns, and guides

The code is meant to be read and learned from, not just used. Star the repo if you find it useful! ⭐

---

## Conclusion

The question I started with was: can you build a multi-agent system that doesn't become an unmaintainable mess?

The answer is yes - and the approach isn't novel. It's applying the same principles we've used for decades in software engineering: layered architecture, separation of concerns, Domain-Driven Design, clear boundaries between components.

What's interesting is that these patterns map so naturally to agent systems. The DDD layers emerge organically. The Anti-Corruption Layer concept perfectly describes the tools/services split. Bounded contexts explain why we group YouTube search and transcript fetching together.

Agent systems aren't magic. They're software systems with a particular interface (natural language) and a particular component (an LLM). The same engineering discipline applies.

The key insight specific to agents: **tools and services have fundamentally different responsibilities**. Tools are an adapter layer - translating between the LLM's world (simple parameters, string outputs) and your domain's world (rich objects, business logic). Conflating them creates the mess I see in most agent code. Separating them unlocks clean, testable, maintainable systems.

---

**What's Next**: This architecture works well for an orchestrator pattern, where a central agent coordinates specialists. But what happens when workflows get complex and the orchestrator becomes a bottleneck? In Part 2, we'll explore what happens when you remove the central coordinator entirely - when every agent understands the goal and decides for itself what should happen next.

---

*The code for this project is available on GitHub. All patterns described here are implemented in the reference codebase.*
