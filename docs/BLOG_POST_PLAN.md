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
| Working code | src/youtube_agent_orchestrator/ | Reference implementation |
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

---

# Part 2: V2 Multi-Agent Coordination Patterns

## Proposed Title Options

1. "Beyond the Orchestrator: Four Patterns for Multi-Agent Coordination"
2. "When Agents Talk to Each Other: Building Autonomous Agent Chains"
3. "From Central Control to Emergent Behavior: Multi-Agent Patterns in Practice"

---

## Target Audience

Same as Part 1, plus:
- Engineers who've built basic agent systems and want to scale
- Architects evaluating orchestration vs autonomous patterns
- Teams building complex workflows with multiple specialized agents

---

## Key Takeaways for Readers

1. The orchestrator pattern isn't the only way—four patterns with different tradeoffs
2. When to use static DAG planning vs emergent autonomous handoffs
3. How to implement semantic intent routing for agent-to-agent communication
4. Practical loop detection and error handling for autonomous agent chains

---

## Blog Post Outline (Part 2)

### 1. Introduction: The Orchestrator's Limitation (400 words)

**Hook**: In Part 1, we built a YouTube research assistant with an orchestrator coordinating four specialized agents. It works—but there's a fundamental limitation.

**The Problem**:
```
V1: User → Orchestrator → Agent A → Orchestrator → Agent B → Orchestrator → User
```
The orchestrator sees every step. It's a bottleneck. What if agents could talk to each other?

**The Vision**:
```
V2: User → Agent A → Agent B → Agent C → User
```
Agents hand off directly. The coordinator only sees the initial request and final result.

**What we'll explore**: Four patterns from centralized to fully autonomous.

### 2. The Patterns Overview (300 words)

**Visual comparison table** (post-refactor):

| Pattern | Control | Best For | Complexity | Command |
|---------|---------|----------|------------|---------|
| V1 Orchestrator | LLM decides each step | Conversational reasoning | Medium | `youtube-agent` |
| V2 Unified (Autonomous + Queue) | Agents reason + self-select from queue | Adaptive goal-driven tasks | Medium | `youtube-agent-v2` |
| Planner + DAG | LLM plans upfront | Complex multi-step | High | `youtube-agent-planner` |

**The key question**: "Who decides what happens next?"

**Note on original patterns**: We initially explored four patterns (Dispatcher, Self-Selection, Planner, Autonomous). During implementation, we learned that Dispatcher and Self-Selection both solved task routing but didn't compose well with autonomous reasoning. The refactored architecture merges the best ideas:
- **Event-driven queue** from Self-Selection (zero CPU when idle, natural load balancing)
- **Goal reasoning and handoffs** from Autonomous (agents decide what's next)
- **Planner + DAG** separated as its own tool for explicit planning use cases

### 3. Pattern 1: Event-Driven Self-Selection (400 words)

**Concept**: Agents wait for queue notifications and compete to claim tasks they can handle. Unlike polling-based approaches, this uses `asyncio.Event` for zero CPU usage when idle.

**Architecture diagram**:
```
User → Event-Driven Task Queue
            ↓ (notification)
    A  B  C  (agents wake up)
            ↓
    SearchAgent claims it
```

**Code example**: `SelfSelectingPool` with event-driven claiming

**Key insight**: Event-driven notifications solve the polling overhead problem (original self-selection polled every 50ms).

**When to use**:
- Any youtube_autonomous_agents task (this is the foundation)
- Scalable systems with many agents
- Need natural load balancing

### 4. Pattern 2: Planner + DAG (600 words)

**Concept**: An LLM Planner analyzes the request upfront and creates a dependency graph. A DAGExecutor runs it.

**The breakthrough**: The plan is **inspectable data**, not implicit LLM reasoning.

**Example DAG** (from E2E test):
```
[Plan] Goal: Find a YouTube video, get transcript, summarize
  → yt_search: Search YouTube for asyncio basics
  → fetch_transcript: Get transcript (after: yt_search)
  → summarize: Summarize key points (after: fetch_transcript)
```

**Variable resolution**: Steps reference earlier results with `$step_id.field`

**Code walkthrough**:
1. `PlannerAgent.create_plan()` - LLM generates DAG as JSON
2. `DAGExecutor.execute()` - Runs steps respecting dependencies
3. `Session` - Stores intermediate results for variable resolution

**Re-planning on failure**: When a step fails, Planner can revise the plan using partial results.

**When to use**:
- Complex multi-step workflows
- Need visibility into execution plan
- Parallel execution of independent steps matters

**E2E output example** (from test run):
```
[Planning...] Creating execution plan ✓ (3 steps)
[Plan] Goal: Find a YouTube video about Python asyncio basics...
  → yt_search_asyncio_basics: Search YouTube...
  → fetch_transcript_asyncio_video: Fetch the transcript (after: yt_search)
  → summarize_asyncio_key_points: Summarize... (after: fetch_transcript)
[Executing...] Running DAG
## Key points summary...
```

### 5. Pattern 3: Autonomous Agent Chains via Queue (800 words)

**Concept**: Each agent receives the original **goal** plus accumulated **state**. Agents reason about what to do next and post handoffs to the queue using **natural language intent**. The next capable agent self-selects to continue.

**The core insight**: Every agent thinks. Handoffs flow through a shared queue, enabling natural load balancing and scalability.

**Architecture** (unified autonomous + queue):
```
User: "Find videos, get transcript, summarize"
           ↓
    Task Queue (event-driven)
           ↓ (notify agents)
    SearchAgent claims task
           ↓
    Thinks: "Goal needs videos. I can search."
    Executes search
    Thinks: "Goal also needs transcripts. Hand off."
    Posts handoff to queue
           ↓
    Task Queue (with intent + state)
           ↓ (notify agents)
    TranscriptAgent claims task
           ↓
    ... continues until complete
```

**Key components**:

1. **HandoffResult**: Agents return either `complete(result)` or `handoff(intent, state)`
```python
if goal_satisfied:
    return HandoffResult.complete(my_result)
else:
    return HandoffResult.handoff(
        intent="Summarize these transcripts focusing on...",
        state={**current_state, "transcripts": my_result}
    )
```

2. **Intent Router**: Maps natural language intents to capable agents
```python
# Agent hands off with: "Get the spoken words from this video"
# Router asks LLM: "Which agent should handle the FIRST step?"
# LLM responds: "transcript"
```

3. **Loop Detection**: Prevents infinite handoff cycles
```python
if loop_detector.check_for_loop(execution_path):
    return PartialResult(error="Loop detected: search → transcript → search")
```

**E2E output example** (from test run):
```
[Autonomous] Starting agent chain...
[Path] search(handoff) → transcript(handoff) → summarize(complete)
## Results: Python asyncio basics...
```

**The fix we discovered**: For multi-step queries, the LLM router must identify the **first** step, not evaluate if each agent can handle the entire query.

**When to use**:
- Adaptive workflows where the path isn't known upfront
- Exploratory tasks that may evolve
- Building toward truly autonomous systems

### 6. Choosing the Right Pattern (400 words)

**Decision flowchart** (simplified post-refactor):
```
Do you need an inspectable plan upfront?
├── Yes → youtube-agent-planner (Planner + DAG)
└── No → Is it conversational with back-and-forth?
          ├── Yes → youtube-agent (V1 Orchestrator)
          └── No → youtube-agent-v2 (Autonomous + Queue)
```

**Performance comparison**:

| Metric | V1 Orchestrator | Planner + DAG | V2 Autonomous |
|--------|-----------------|---------------|---------------|
| LLM calls | N (per step) | 1 planning + N execution | 2N (routing + reasoning) |
| Latency | Per-step LLM | Plan overhead upfront | Per-step overhead |
| Adaptability | High (conversational) | Re-plan on failure | Continuous |
| Debuggability | Medium | Very high (inspect DAG) | Medium (execution path) |
| CPU when idle | N/A | N/A | Zero (event-driven) |

### 8. Implementation Tips (400 words)

**Structured results for DAG variable resolution**:
- Agents must return dictionaries, not formatted strings
- Plan references like `$search.results[0].video_id` need structured data

**Agent name validation in Planner**:
- LLMs may invent agents ("extract_parameters" instead of "summarize")
- Validate step agent names against registry before execution

**Intent routing priorities**:
- Keyword matching is fast but may produce ties
- LLM fallback should ask "which agent handles the FIRST step?"

**Session state management**:
- Track execution path for debugging: `search(handoff) → transcript(complete)`
- Store intermediate results for variable resolution
- Record timing for performance analysis

### 8. Conclusion (200 words)

**Summary** (post-refactor):
- **V1 Orchestrator** (`youtube-agent`): Great for conversational reasoning with back-and-forth
- **V2 Autonomous + Queue** (`youtube-agent-v2`): Event-driven self-selection + autonomous handoffs. The unified pattern for goal-driven batch tasks
- **Planner + DAG** (`youtube-agent-planner`): Inspectable plans, parallel execution, re-planning. Separate tool for explicit planning

**What we learned**: Four patterns was too many. Dispatcher and Self-Selection both solved task routing but didn't compose with autonomous reasoning. The refactored architecture takes the best ideas:
- Event-driven queue (from Self-Selection) for efficiency
- Autonomous handoffs (from Autonomous pattern) for adaptability
- Planner as a separate tool when explicit planning is needed

**The meta-lesson**: Start simple, then combine patterns based on real needs. Choose based on:
- Do you need inspectable plans? → Planner
- Is it conversational? → V1 Orchestrator
- Is it goal-driven batch processing? → V2 Autonomous

**What's next**: Testing strategies for multi-agent systems, production deployment considerations.

---

## Code Samples to Include (Part 2)

1. **Four patterns comparison table** (visual)
2. **DAG example JSON** (from Planner output)
3. **HandoffResult usage** (agent decision code)
4. **Intent router prompt** (LLM-based routing)
5. **Execution path output** (CLI screenshot)
6. **Loop detection logic** (simplified)

---

## Supporting Materials (Part 2)

| Material | Source | Purpose |
|----------|--------|---------|
| Pattern implementations | `src/youtube_autonomous_agents/patterns/` | Reference code |
| Session + execution tracking | `src/youtube_autonomous_agents/core/session.py` | State management |
| Intent routing | `src/youtube_autonomous_agents/core/intent_router.py` | Semantic routing |
| E2E test outputs | CLI runs | Real-world examples |

---

## Estimated Length (Part 2)

~4,000 words (15-18 minute read)

---

## Series Structure

| Post | Focus | Length |
|------|-------|--------|
| Part 1 | Architecture: layers, tools vs services, testing | ~3,000 words |
| Part 2 | Coordination: four patterns, autonomous agents | ~4,000 words |
| Part 3 (future) | Production: deployment, monitoring, error handling | TBD |
