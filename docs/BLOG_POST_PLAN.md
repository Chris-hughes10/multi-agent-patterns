# Blog Post Series: Building Multi-Agent Systems with the Claude Agent SDK

## Series Overview

A two-part series exploring the architecture and coordination patterns for production multi-agent systems. Part 1 covers foundational architecture; Part 2 explores the journey from centralized orchestration to autonomous agent coordination.

---

## Target Audience

- Software engineers exploring AI agent frameworks
- Developers familiar with Python but new to multi-agent systems
- Teams evaluating agent frameworks (Claude Agent SDK, LangChain, CrewAI)
- Engineers who've built basic agent systems and want to scale

---

## Part 1: Architecting Multi-Agent Systems

### Title Options

1. "Architecting Multi-Agent Systems: Lessons from Building a YouTube Research Assistant"
2. "Tools vs Services: A Clean Architecture for AI Agents"
3. "Building Production-Ready AI Agents with the Claude Agent SDK"

### Key Takeaways

1. How to structure a multi-agent application with clear separation of concerns
2. The difference between tools (LLM interface) and services (business logic)
3. Why domain-driven organization matters for maintainability
4. Practical testing strategies for agent-based systems

### Outline

#### 1. Introduction (300 words)

**Hook**: The AI agent landscape is crowded - but most tutorials focus on "hello world" demos, not production architecture.

**Thesis**: This post shares architectural patterns we discovered building a YouTube transcript research assistant - patterns that apply regardless of which framework you choose.

**What we built**: A multi-agent system that searches YouTube, fetches transcripts, generates summaries, and exports to markdown. Four specialized agents working together.

#### 2. The Architecture Challenge (400 words)

**The problem**: Agent code gets messy fast. Tools, services, models, and agent logic all mixed together.

**Our initial mess**: Show a "before" snippet where everything was in one file.

**The insight**: LLM-callable functions have different concerns than business logic. Separating them unlocks testability and reusability.

**The layered architecture diagram**:
```
cli → agents → tools → services → models → infra
```

#### 3. Tools vs Services: The Key Distinction (600 words)

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

#### 4. Domain-Driven Organization (400 words)

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

#### 5. Agent Design: Single Responsibility (400 words)

**Each agent has ONE job**:

| Agent | Does | Does NOT |
|-------|------|----------|
| SearchAgent | Find videos | Fetch transcripts |
| TranscriptAgent | Fetch/cache transcripts | Summarize |
| SummarizeAgent | Generate summaries | Fetch from YouTube |
| WriterAgent | Write files | Any YouTube operations |

**The Orchestrator pattern**: Coordinates but doesn't do real work.

**Context injection**: How `TranscriptContextProvider` tells the orchestrator what's already cached, enabling smart decisions.

#### 6. Testing Strategy (500 words)

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

#### 7. Lessons Learned (300 words)

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

#### 8. Conclusion (200 words)

**Summary**: Clean architecture for agents = layered design + tools/services split + domain-driven organization + minimal mocking.

**Call to action**: Link to the GitHub repo, invite feedback.

**What's next**: Part 2 explores what happens when you remove the central coordinator entirely.

### Estimated Length

~3,000 words (10-12 minute read)

---

## Part 2: From Orchestrator to Autonomous Agents

### Title Options

1. "From Orchestrator to Autonomous: What Happens When Every Agent Thinks"
2. "Removing the Coordinator: Building Self-Organizing Agent Systems"
3. "Beyond Central Control: Autonomous Multi-Agent Patterns in Practice"

### Key Takeaways

1. Why centralized orchestration becomes a bottleneck for complex workflows
2. How to design agents that reason about goals, not just execute commands
3. Implementing event-driven coordination with zero polling overhead
4. Parallel execution patterns with decentralized fan-out/fan-in

### Outline

#### 1. Introduction: The Orchestrator's Limitation (400 words)

**Hook**: In Part 1, we built a YouTube research assistant with an orchestrator coordinating four specialized agents. It works - but there's a fundamental limitation.

**The Problem**:
```
V1: User → Orchestrator → Agent A → Orchestrator → Agent B → Orchestrator → User
```
The orchestrator sees every step. It's a bottleneck. Context grows with each round-trip. What if agents could coordinate directly?

**The Vision**:
```
V2: User → Agent A → Agent B → Agent C → User
```
Agents hand off directly. No central coordinator managing every interaction.

**The journey**: We explored several approaches - dispatcher patterns, explicit planning, capability-based routing - before arriving at a simpler insight: give every agent the goal, let them decide what's next.

#### 2. The Core Shift: Every Agent Thinks (500 words)

**The old model**: One "smart" orchestrator coordinates "dumb" workers. The orchestrator decides what each agent should do.

**The new model**: Every agent receives the original goal plus accumulated state. Each agent reasons: "Can I complete this goal, or should someone else continue?"

**Why this matters**:
- No context bottleneck (state flows forward, not back to center)
- Agents adapt to what they find (search results inform next steps)
- Adding new agents doesn't require updating orchestrator logic

**Code example**: The execute_autonomous interface
```python
async def execute_autonomous(
    self,
    goal: str,        # Original user request (constant)
    state: dict,      # Results from previous agents
) -> HandoffResult:
    # Do my work
    results = await self.do_specialized_work(state)

    # Reason about the goal
    if self._goal_is_satisfied(goal, results):
        return HandoffResult.complete(results)
    else:
        return HandoffResult.handoff(
            intent="What needs to happen next",
            state={**state, "my_results": results}
        )
```

#### 3. Structured Completion Signaling (400 words)

**The problem with implicit completion**: Most frameworks return strings or dicts. How do you know if the agent is done, or if it needs another agent?

**Our solution**: Explicit result types that force clear signaling

```python
# Three possible outcomes - no ambiguity
HandoffResult.complete(result)           # I'm done, here's the answer
HandoffResult.handoff(intent, state)     # Someone else continues
HandoffResult.fan_out(intents, join)     # Parallel execution, then merge
```

**Why types matter**:
- Compile-time clarity about workflow topology
- Pool can handle each case differently
- No string parsing to determine next steps

**PartialResult and OperationTimeout**: Failures as first-class domain objects
```python
# Agents can reason about failures, not just catch exceptions
if isinstance(result, OperationTimeout):
    # Maybe use a fallback, or hand off with partial data
    return HandoffResult.handoff(
        intent="Continue with what we have",
        state={**state, "timeout_context": result.to_dict()}
    )
```

#### 4. Event-Driven Coordination (500 words)

**The naive approach**: Agents poll a queue in a loop. Works, but wastes CPU cycles when idle.

**Our approach**: Event-driven notification with asyncio

```python
# Agents sleep until notified - zero CPU when idle
while not shutdown:
    has_task = await registry.wait_for_task_available(timeout=0.5)
    if not has_task:
        continue

    task = await registry.peek_next_task()
    if agent.can_handle(task):
        claimed = await registry.try_claim(task.id, agent.name)
        if claimed:
            await execute_task(agent, task)
```

**Key patterns**:
- `asyncio.Event` for task notifications
- Atomic claiming prevents race conditions
- Agents self-select based on capabilities

**Why this matters for production**:
- Scales to many agents without CPU overhead
- Natural load balancing (busy agents claim less)
- Easy to add/remove agents dynamically

#### 5. Intent Routing: Why Keywords Aren't Enough (400 words)

**The challenge**: When an agent hands off with "Get transcripts AND summarize", which agent handles it?

**Keyword matching fails**: Both transcript and summarize agents match. Who goes first?

**LLM-based routing**: Ask the LLM to identify the FIRST step
```python
prompt = """
Intent: "Get transcripts for these videos AND summarize the key points"
Available agents: search, transcript, summarize, writer

Which agent should handle the FIRST step of this intent?
"""
# LLM responds: "transcript" (get transcripts first, then summarize)
```

**Three-tier routing priority**:
1. Explicit routing (task was routed by previous LLM call)
2. Capability matching (fast, deterministic)
3. LLM fallback (for complex multi-step intents)

#### 6. Parallel Execution: Decentralized Fan-Out/Fan-In (600 words)

**The use case**: "Search both Chuds BBQ AND Fork & Embers for pork loin recipes"

**Two independent searches** should run in parallel, then merge results.

**The pattern**:
```python
# Any agent can trigger parallel execution
return HandoffResult.fan_out(
    intents=[
        "Search Chuds BBQ for pork loin",
        "Search Fork and Embers for pork loin"
    ],
    join_intent="Combine search results and get transcripts",
    state={"query": "pork loin kamado"}
)
```

**How it works**:
1. Agent returns `fan_out` with multiple intents
2. Pool creates a TaskGroup to track parallel tasks
3. Each intent posted as separate task, routed independently
4. When all complete, pool posts the join task automatically
5. Join task receives `parallel_results` with all outputs

**Key design decision**: Parallel tasks always complete (never hand off). This ensures results are captured before the join.

**Interleaving for diversity**: When combining parallel search results, we interleave [A1, B1, A2, B2...] instead of concatenating [A1, A2..., B1, B2...]. This ensures variety when selecting top N results.

#### 7. Goal-Aware Reasoning in Practice (500 words)

**Show a real agent's reasoning**: SearchAgent deciding whether to complete or hand off

```python
async def _reason_about_goal(self, goal: str, search_results: dict) -> dict:
    prompt = f"""
    USER'S GOAL: "{goal}"

    WHAT I DID: Searched YouTube and found these videos:
    {video_titles}

    Is the goal satisfied, or do they need more?

    Consider:
    - If they just want to find videos → SATISFIED
    - If they want information FROM the videos → need TRANSCRIPTS
    - If they want analysis or summaries → need TRANSCRIPTS then SUMMARIZATION
    """
```

**The power of goal-awareness**: The agent doesn't just execute a command - it understands the user's intent and decides the appropriate next step.

**Graceful degradation**: If reasoning times out, default to handing off (safer to do more work than less).

#### 8. Choosing Your Pattern (300 words)

**Decision framework**:

| Question | Pattern |
|----------|---------|
| Conversational with back-and-forth? | V1 Orchestrator |
| Goal-driven batch processing? | V2 Autonomous |
| Need inspectable execution plan? | Planner + DAG (separate tool) |

**Performance characteristics**:

| Metric | Orchestrator | Autonomous |
|--------|--------------|------------|
| LLM calls | N (per step) | 2N (routing + reasoning) |
| Context growth | Accumulates at center | Flows forward |
| Adaptability | High (conversational) | High (goal-aware) |
| Parallelism | Manual | Built-in fan-out |

#### 9. Conclusion (200 words)

**The insight**: Removing the central coordinator doesn't mean chaos - it means every agent takes responsibility for understanding the goal.

**What we gained**:
- No context bottleneck
- Natural parallelism
- Agents that adapt to what they find

**What we learned**: Start simple. We explored several patterns before realizing the core insight was simpler than we thought: give every agent the goal, let them reason about what's next.

**The meta-pattern**: Good multi-agent architecture isn't about clever coordination - it's about clear contracts (HandoffResult), explicit state passing, and agents that understand intent, not just commands.

### Estimated Length

~4,000 words (15-18 minute read)

---

## Code Samples Summary

### Part 1
1. Layered architecture diagram (ASCII)
2. Tool vs Service comparison (side-by-side)
3. Domain-driven services structure (file tree)
4. Agent responsibility table
5. Test with mock boundary (code snippet)

### Part 2
1. Orchestrator vs Autonomous flow diagrams
2. HandoffResult type definition
3. Event-driven watcher loop
4. Intent routing prompt
5. Fan-out/fan-in flow diagram
6. Goal reasoning example

---

## Supporting Materials

| Material | Source | Purpose |
|----------|--------|---------|
| Full architecture | README.md | Visual overview |
| Design rationale | DESIGN_PHILOSOPHY.md | Detailed explanations |
| V2 implementation | V2_IMPLEMENTATION_PLAN.md | Current state |
| Event loop guide | EVENT_LOOP_EXPLAINED.md | Async patterns |
| Working code | src/youtube_autonomous_agents/ | Reference |

---

## Series Structure

| Post | Focus | Length |
|------|-------|--------|
| Part 1 | Architecture: layers, tools vs services, testing | ~3,000 words |
| Part 2 | Coordination: orchestrator → autonomous, parallelism | ~4,000 words |
| Part 3 (future) | Production: deployment, monitoring, error handling | TBD |
