# Blog Post Plan: Building Multi-Agent Systems with Microsoft Agent Framework

## Target Audience

- Software engineers exploring AI agent frameworks
- Developers familiar with Python but new to multi-agent systems
- Teams evaluating Microsoft Agent Framework vs alternatives (LangChain, CrewAI)

## Key Takeaways for Readers

1. How to structure a multi-agent application with clear separation of concerns
2. The difference between tools (LLM interface) and services (business logic)
3. Why domain-driven organization matters for maintainability
4. Practical testing strategies for agent-based systems

---

## Proposed Title Options

1. "Architecting Multi-Agent Systems: Lessons from Building a YouTube Research Assistant"
2. "Tools vs Services: A Clean Architecture for AI Agents"
3. "Building Production-Ready AI Agents with Microsoft Agent Framework"

---

## Blog Post Outline

### 1. Introduction (300 words)

**Hook**: The AI agent landscape is crowded—LangChain, CrewAI, AutoGen, and now Microsoft's unified Agent Framework. But most tutorials focus on "hello world" demos, not production architecture.

**Thesis**: This post shares architectural patterns we discovered building a YouTube transcript research assistant—patterns that apply regardless of which framework you choose.

**What we built**: A multi-agent system that searches YouTube, fetches transcripts, generates summaries, and exports to markdown. Four specialized agents coordinated by an orchestrator.

### 2. The Architecture Challenge (400 words)

**The problem**: Agent code gets messy fast. Tools, services, models, and agent logic all mixed together.

**Our initial mess**: Show a "before" snippet where everything was in one file.

**The insight**: LLM-callable functions have different concerns than business logic. Separating them unlocks testability and reusability.

**The layered architecture diagram**:
```
cli → agents → tools → services → models → infra
```

### 3. Tools vs Services: The Key Distinction (600 words)

**This is the core insight of the post.**

**Tools = LLM Interface**
- Accept simple parameters (strings, numbers)
- Return formatted strings the LLM can reason about
- Are stateless, thin wrappers

**Services = Business Logic**
- Return rich domain objects
- Are reusable from CLI, tests, other services
- May maintain state or connections

**Code example**: Show the flow from tool → service → model

```python
# Tool (what the LLM calls)
def fetch_video_transcript(video_id: str) -> str:
    result = fetch_transcript(video_id)  # calls service
    return f"Title: {result.metadata.title}\n\nTranscript:\n{result.transcript.full_text}"

# Service (the real implementation)
def fetch_transcript(video_id: str) -> TranscriptResult:
    fetcher = YouTubeTranscriptFetcher()
    return fetcher.fetch(video_id)  # returns rich object
```

**Why this matters**:
- Services can be called from anywhere (CLI, tests, scripts)
- Tools format output for LLM consumption
- Testing becomes straightforward

### 4. Domain-Driven Organization (400 words)

**The question**: Should `services/` be organized by function or domain?

**Our choice**: Domain (DDD-aligned)

```
services/
├── youtube.py      # Search + transcript fetching (same domain)
├── storage.py      # Persistence
└── summarizer.py   # AI summarization
```

**The litmus test**: "If I replaced this external system, what would change?"
- Replace YouTube → change `youtube.py`
- Replace JSON storage → change `storage.py`
- Replace Azure OpenAI → change `summarizer.py`

**Why not split by function?** Search and transcript fetching share domain concepts (video ID, channel). They belong together.

### 5. Agent Design: Single Responsibility (400 words)

**Each agent has ONE job**:

| Agent | Does | Does NOT |
|-------|------|----------|
| SearchAgent | Find videos | Fetch transcripts |
| TranscriptAgent | Fetch/cache transcripts | Summarize |
| SummarizeAgent | Generate summaries | Fetch from YouTube |
| WriterAgent | Write files | Any YouTube operations |

**The Orchestrator pattern**: Coordinates but doesn't do real work.

**Context injection**: How `TranscriptContextProvider` tells the orchestrator what's already cached, enabling smart decisions.

### 6. Testing Strategy (500 words)

**Kent Beck's approach**: Only mock external or long-running services.

**The mock boundary**:
```
agents → tools → services  ← test with real code
                    ↓
              External APIs  ← mock here
```

**What we mock**:
- YouTube transcript API calls
- Azure OpenAI API calls

**What we DON'T mock**:
- `TranscriptStorage` (use real storage with temp directory)
- Service classes (inject mock clients instead)

**Code example**: Show a test that uses real services with mocked external client.

**Why this approach**:
- Higher confidence (real code paths)
- Less brittle (fewer mocks to maintain)
- Faster feedback (failures are real problems)

### 7. Lessons Learned (300 words)

**What worked well**:
- Separating tools from services early saved refactoring pain
- Domain-driven services made the codebase navigable
- Minimal mocking caught real integration bugs

**What we'd do differently**:
- Define the layered architecture before writing code
- Create a `services/` package from day one

**Framework-agnostic takeaways**:
- These patterns apply to LangChain, CrewAI, or custom solutions
- The key is separating "LLM interface" from "business logic"

### 8. Conclusion (200 words)

**Summary**: Clean architecture for agents = layered design + tools/services split + domain-driven organization + minimal mocking.

**Call to action**: Link to the GitHub repo, invite feedback.

**What's next**: Potential follow-up posts on context injection, orchestration patterns, or production deployment.

---

## Code Samples to Include

1. **Layered architecture diagram** (ASCII art)
2. **Tool vs Service comparison** (side-by-side code)
3. **Domain-driven services structure** (file tree)
4. **Agent responsibility table**
5. **Test with mock boundary** (code snippet)
6. **Context injection example** (simplified)

---

## Supporting Materials

| Material | Source | Purpose |
|----------|--------|---------|
| Full architecture diagram | README.md | Visual overview |
| Design rationale | DESIGN_PHILOSOPHY.md | Detailed explanations |
| Working code | src/youtube_agent/ | Reference implementation |
| Test examples | tests/ | Testing patterns |

---

## Estimated Length

~3,000 words (10-12 minute read)

---

## Potential Follow-up Posts

1. **"Context Injection for Smarter Agents"** - Deep dive on TranscriptContextProvider
2. **"Testing AI Agents Without Mocking Everything"** - Expanded testing strategies
3. **"From Prototype to Production"** - Deployment, monitoring, error handling
4. **"Comparing Agent Frameworks"** - Same app built with LangChain, CrewAI, MS Agent Framework
