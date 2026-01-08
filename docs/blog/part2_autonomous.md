# From Orchestrator to Autonomous: What Happens When Every Agent Thinks

In Part 1, we built a YouTube research assistant with an orchestrator coordinating four specialized agents. The orchestrator received user requests, delegated to specialists, collected results, and synthesized responses. It worked well for conversational interactions.

But as our workflows grew more complex, we noticed a pattern: the orchestrator was becoming a bottleneck.

```
V1: User → Orchestrator → Agent A → Orchestrator → Agent B → Orchestrator → User
```

Every step routes through the center. The orchestrator's context grows with each round-trip. Adding new capabilities means updating the orchestrator's instructions. What if agents could coordinate directly?

```
V2: User → Agent A → Agent B → Agent C → User
```

This post explores the journey from centralized orchestration to autonomous agent coordination. We'll cover the patterns we explored, what worked, and the surprisingly simple insight that made it all click.

## In this article, we shall cover:

- Why centralized orchestration becomes a bottleneck for complex workflows
- How to design agents that reason about goals, not just execute commands
- Implementing event-driven coordination with zero polling overhead
- Parallel execution patterns with decentralized fan-out/fan-in
- When to use orchestration vs autonomous patterns

---

## The Orchestrator's Limitation

The orchestrator pattern from Part 1 has a fundamental constraint: **the coordinator sees every step**.

Consider a multi-step research task: "Find videos about Kamado cooking, get their transcripts, summarize the key temperatures and times, and save to a markdown file."

With an orchestrator:

1. User → Orchestrator: "Find videos about Kamado cooking..."
2. Orchestrator → SearchAgent: "Search for Kamado cooking videos"
3. SearchAgent → Orchestrator: "Found 5 videos: [list]"
4. Orchestrator → TranscriptAgent: "Get transcripts for these videos"
5. TranscriptAgent → Orchestrator: "Here are the transcripts: [text]"
6. Orchestrator → SummarizeAgent: "Summarize temperatures and times"
7. SummarizeAgent → Orchestrator: "Key findings: [summary]"
8. Orchestrator → WriterAgent: "Save this to markdown"
9. WriterAgent → Orchestrator: "Saved to output/kamado_notes.md"
10. Orchestrator → User: "Done! Here's your summary..."

The orchestrator participates in every exchange. Its context window accumulates all intermediate results. For complex workflows, this becomes expensive - both in tokens and in the cognitive load of maintaining coherent reasoning across many steps.

We explored several alternatives:
- **Dispatcher pattern**: A router that assigns tasks but doesn't coordinate results
- **Capability-based routing**: Match tasks to agents by declared capabilities
- **Explicit planning**: An LLM generates a DAG of steps upfront

Each had merits, but they also had complexity. The dispatcher still needed to understand all agents. Capability matching broke down for ambiguous intents. Planning required re-planning when things changed.

The insight that simplified everything: **give every agent the goal, and let them decide what's next**.

---

## The Core Shift: Every Agent Thinks

In the orchestrator model, we had one "smart" coordinator directing "dumb" workers. The orchestrator knew the goal; agents just executed commands.

In the autonomous model, every agent receives two things:
1. **The original goal** - what the user actually asked for
2. **Accumulated state** - results from previous agents

Each agent then reasons: "Given this goal and what we have so far, can I complete the request? Or should someone else continue?"

```python
async def execute_autonomous(
    self,
    goal: str,        # Original user request (stays constant)
    state: dict,      # Results from previous agents (grows)
) -> HandoffResult:
    """Execute with awareness of the overall goal."""

    # Do my specialized work
    results = await self.do_my_work(state)

    # Reason about whether the goal is satisfied
    if self._goal_is_satisfied(goal, results):
        return HandoffResult.complete(results)
    else:
        return HandoffResult.handoff(
            intent="What needs to happen next",
            state={**state, "my_results": results}
        )
```

This is philosophically different from most agent frameworks. The agent isn't just executing a command - it's understanding intent and deciding the appropriate next step.

### Why This Matters

**No context bottleneck**: State flows forward through the chain, not back to a central point. Each agent only sees what's relevant.

**Adaptive workflows**: Agents respond to what they find. If search returns no results, the SearchAgent can hand off with "Try a different query" rather than blindly continuing.

**Easy extensibility**: Adding a new agent doesn't require updating a central orchestrator. If the new agent can handle certain intents, it will be routed tasks naturally.

---

## Structured Completion Signaling

Most frameworks return strings or dictionaries from agent calls. This creates ambiguity: How do you know if the agent is done, or if it expects another agent to continue?

We solved this with explicit result types:

```python
@dataclass
class HandoffResult:
    """Result from an agent - complete, handoff, or fan_out."""

    action: Literal["complete", "handoff", "fan_out"]

    # If action == "complete"
    result: Any | None = None

    # If action == "handoff"
    intent: str | None = None

    # If action == "fan_out"
    intents: list[str] | None = None
    join_intent: str | None = None

    # Shared state for handoff and fan_out
    state: dict[str, Any] = field(default_factory=dict)
```

Three possible outcomes, no ambiguity:

```python
# I'm done - here's the answer
return HandoffResult.complete({"summary": "Key temperatures: 225°F for 4 hours..."})

# Someone else needs to continue
return HandoffResult.handoff(
    intent="Summarize these transcripts focusing on cooking times",
    state={**state, "transcripts": my_transcripts}
)

# Multiple things can happen in parallel, then merge
return HandoffResult.fan_out(
    intents=["Search channel A", "Search channel B"],
    join_intent="Combine results and get transcripts",
    state={"query": "pork loin"}
)
```

The validation is built into the type:

```python
def __post_init__(self):
    if self.action == "complete" and self.result is None:
        raise ValueError("Complete action requires a result")
    if self.action == "handoff" and self.intent is None:
        raise ValueError("Handoff action requires an intent")
    if self.action == "fan_out" and len(self.intents or []) < 2:
        raise ValueError("Fan out requires at least 2 intents")
```

No string parsing. No conventions about special return values. The type system enforces clarity.

### Failures as First-Class Domain Objects

We extended this pattern to handle failures gracefully:

```python
@dataclass
class OperationTimeout:
    """Context for a timed-out operation."""
    operation: str
    timeout_seconds: float
    context: dict[str, Any]
    suggested_fallback: str | None = None

@dataclass
class PartialResult:
    """Result when execution cannot complete fully."""
    error: str
    partial_data: dict[str, Any]
    completed_steps: list[str]
```

Now agents can reason about failures:

```python
result = await self._call_with_timeout(
    self._reason_about_goal(goal, data),
    operation="goal_reasoning",
    timeout=30.0,
    suggested_fallback="Use keyword matching instead"
)

if isinstance(result, OperationTimeout):
    # Reasoning timed out - use fallback logic
    return HandoffResult.handoff(
        intent="Continue with available data",
        state={**state, "timeout_context": result.to_dict()}
    )
```

This is much better than try/except scattered everywhere. The agent can make an informed decision about how to proceed.

---

## Event-Driven Coordination

With agents that can hand off to each other, we need a coordination mechanism. The naive approach is a polling loop:

```python
# Naive: agents poll constantly
while True:
    task = queue.get_nowait()
    if task and self.can_handle(task):
        await self.execute(task)
    await asyncio.sleep(0.05)  # Poll every 50ms
```

This wastes CPU cycles when the queue is empty - which, in a bursty workload, is most of the time.

### Event-Driven with asyncio

Python's `asyncio` provides the building blocks for efficient coordination. We use events for notifications and atomic operations for task claiming:

```python
class SelfSelectingPool:
    """Pool where agents autonomously watch and claim tasks."""

    async def _agent_watcher(self, agent: BaseAgent) -> None:
        """Each agent runs this loop independently."""

        while not self._shutdown.is_set():
            # Wait for notification - zero CPU when idle
            has_task = await self._registry.wait_for_task_available(
                timeout=0.5
            )

            if not has_task:
                continue  # Timeout, check shutdown and wait again

            # Peek at the next unclaimed task
            task = await self._registry.peek_next_task()
            if task is None:
                continue  # Another agent claimed it

            # Can I handle this?
            if not agent.can_handle(task):
                continue  # Not for me

            # Try to claim it (atomic operation)
            claimed = await self._registry.try_claim(task.id, agent.name)
            if not claimed:
                continue  # Another agent got it first

            # Execute the task
            await self._execute_task(agent, task)
```

The key insight: `wait_for_task_available` uses `asyncio.Event`, not polling. When a task is added to the queue, the event is set, waking all waiting agents. They compete to claim the task, but only one succeeds (atomic claiming).

### Why This Matters for Production

**Scales to many agents**: Adding more agents doesn't increase CPU usage when idle. They all sleep on the same event.

**Natural load balancing**: Busy agents (still executing a task) don't compete for new work. The idle agents claim tasks first.

**Easy to add/remove agents**: Registration is just adding an agent to the pool. No central configuration to update.

**Zero polling overhead**: The system uses essentially no CPU when waiting for work.

---

## Intent Routing: Why Keywords Aren't Enough

When an agent hands off with an intent like "Get transcripts for these videos AND summarize the key points", which agent handles it?

Keyword matching would see both "transcripts" and "summarize" and match multiple agents. Who goes first?

### LLM-Based Routing

We ask the LLM to identify the **first** step:

```python
class LLMIntentRouter:
    """Routes intents to agents using LLM reasoning."""

    async def find_agent_for_intent(
        self,
        intent: str,
        registry: AgentRegistry
    ) -> BaseAgent | None:

        agent_descriptions = [
            f"- {a.name}: {a.description}"
            for a in registry.all_agents()
        ]

        prompt = f"""Route this intent to the correct agent.

INTENT: "{intent}"

AVAILABLE AGENTS:
{chr(10).join(agent_descriptions)}

IMPORTANT: If the intent has multiple steps, identify which agent
should handle the FIRST step.

Examples:
- "Get transcripts AND summarize" → transcript (get transcripts first)
- "Summarize these transcripts" → summarize (already have transcripts)
- "Search and save results" → search (search first)

Respond with only the agent name."""

        response = await self._client.get_response(prompt)
        agent_name = response.text.strip().lower()

        return registry.get_agent(agent_name)
```

The LLM understands that "get transcripts AND summarize" requires transcripts first. It routes to the transcript agent, which will later hand off to the summarize agent.

### Three-Tier Routing Priority

We use a cascade:

1. **Explicit routing**: If the previous agent specified a target via LLM routing, respect it
2. **Capability matching**: Fast, deterministic matching on declared capabilities
3. **LLM fallback**: For complex or ambiguous intents

```python
def can_handle(self, task: Task) -> bool:
    # Priority 1: Was I explicitly routed this task?
    if task.context.get("routed_to") == self.name:
        return True

    # Priority 2: Do my capabilities match?
    if task.required_capabilities:
        return any(cap in self.capabilities
                   for cap in task.required_capabilities)

    # Priority 3: Intent-based fallback
    intent = task.context.get("intent", "")
    return self._can_handle_intent(intent)
```

This gives us the speed of capability matching for simple cases, with LLM reasoning available for complex multi-step intents.

---

## Parallel Execution: Decentralized Fan-Out/Fan-In

Some tasks are naturally parallel. "Search both Chuds BBQ AND Fork & Embers for pork loin recipes" has two independent searches that can run simultaneously.

### The Pattern

Any agent can trigger parallel execution by returning a fan-out:

```python
return HandoffResult.fan_out(
    intents=[
        "Search Chuds BBQ for pork loin",
        "Search Fork and Embers for pork loin"
    ],
    join_intent="Combine search results and get transcripts",
    state={"query": "pork loin kamado"}
)
```

The pool handles the coordination:

```
User: "Search both channels for pork loin recipes"
                         │
               ┌─────────▼─────────┐
               │    Synthesizer    │  Analyzes: "Two channels = parallel"
               └────────┬──────────┘
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
    [SearchAgent]              [SearchAgent]
    "chuds bbq"               "fork + embers"
          │                           │
          └──────────┬────────────────┘
                     ▼
             [TaskGroup collects]
                     │
                     ▼
           [Join task posted]
                     │
                     ▼
          [Continue chain...]
```

### TaskGroup: Tracking Parallel Completion

We track parallel tasks with a simple data structure:

```python
@dataclass
class TaskGroup:
    """Tracks a group of parallel tasks for fan-out/fan-in."""
    id: str
    task_ids: list[str]
    join_intent: str
    state: dict[str, Any]
    results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return len(self.results) + len(self.errors) >= len(self.task_ids)
```

When all parallel tasks complete, the pool automatically posts the join task:

```python
async def _check_group_completion(self, task: Task) -> None:
    """Check if a completed task's group is now complete."""

    group = self._get_group_for_task(task.id)
    if not group:
        return

    # Record result
    if task.result.success:
        group.results[task.id] = task.result.data
    else:
        group.errors.append(f"Task {task.id}: {task.result.error}")

    # All done?
    if group.is_complete:
        await self._post_join_task(group)
```

### Key Design Decisions

**Parallel tasks always complete**: When `is_parallel_task` is True in the state, agents complete with their results rather than handing off. This ensures results are captured before the join.

```python
# In execute_autonomous:
if state.get("is_parallel_task"):
    # Don't hand off - complete so results are captured
    return HandoffResult.complete(my_results)
```

**Interleaving for diversity**: When combining results from parallel searches, we interleave rather than concatenate:

```python
def _interleave_videos(self, video_lists: list[list[dict]]) -> list[dict]:
    """Interleave [A1, B1, A2, B2...] instead of [A1, A2..., B1, B2...]"""
    interleaved = []
    max_len = max(len(vl) for vl in video_lists)

    for i in range(max_len):
        for video_list in video_lists:
            if i < len(video_list):
                interleaved.append(video_list[i])

    return interleaved
```

This ensures variety when selecting top N results. If we just concatenated, we might get all results from one search before any from another.

---

## Goal-Aware Reasoning in Practice

Let's look at how SearchAgent actually reasons about whether to complete or hand off:

```python
async def _reason_about_goal(
    self, goal: str, search_results: dict
) -> dict:
    """Use LLM to reason about goal satisfaction."""

    video_titles = [r["title"] for r in search_results.get("results", [])[:3]]

    prompt = f"""You are helping decide if a user's goal is satisfied.

USER'S GOAL: "{goal}"

WHAT I DID: Searched YouTube and found these videos:
{chr(10).join(f'- {title}' for title in video_titles)}

QUESTION: Is the goal satisfied, or do they need more?

Consider:
- If they just want to find/discover videos → goal is SATISFIED
- If they want specific information FROM the videos → need TRANSCRIPTS
- If they want analysis, summaries, or key points → need TRANSCRIPTS then SUMMARIZATION

Respond in this exact format:
SATISFIED: yes or no
NEXT_STEP: (only if not satisfied) describe what needs to happen next"""

    response = await client.get_response(prompt)
    # Parse response...
    return {"satisfied": satisfied, "next_step": next_step}
```

The agent doesn't blindly execute a command. It understands:
- "Find videos about cooking" → satisfied with search results
- "Tell me the cooking temperatures from these videos" → need transcripts
- "Summarize the key points" → need transcripts, then summarization

### Graceful Degradation

If goal reasoning times out (LLM latency spikes happen), we default to handing off:

```python
try:
    reasoning = await self._reason_about_goal(goal, results)
except TimeoutError:
    # Safer to do more work than less
    reasoning = {
        "satisfied": False,
        "next_step": "Get transcripts for detailed information"
    }
```

Better to fetch transcripts unnecessarily than to miss information the user wanted.

---

## Choosing Your Pattern

We now have two patterns: the orchestrator from Part 1, and the autonomous pattern from this post. When should you use each?

| Question | Pattern |
|----------|---------|
| Is it conversational with back-and-forth? | Orchestrator |
| Is it goal-driven batch processing? | Autonomous |
| Do you need to inspect the execution plan? | Consider a Planner + DAG approach |
| Are there opportunities for parallelism? | Autonomous (built-in fan-out) |

### Performance Characteristics

| Metric | Orchestrator | Autonomous |
|--------|--------------|------------|
| **LLM calls per step** | 1 (orchestrator decides) | 2 (routing + reasoning) |
| **Context growth** | Accumulates at center | Flows forward |
| **Adaptability** | High (conversational) | High (goal-aware) |
| **Parallelism** | Manual | Built-in |
| **Debugging** | Single point of control | Distributed execution path |

The autonomous pattern has higher per-step LLM costs (routing + goal reasoning), but avoids the context accumulation problem of orchestrators. For long chains, this trade-off often favours autonomous.

---

## Conclusion

The insight that made autonomous agents work was simpler than we expected: **give every agent the goal, let them decide what's next**.

This isn't chaos - it's distributed responsibility. Each agent understands the user's intent and makes an informed decision about whether to complete or continue the chain.

What we gained:
- **No context bottleneck**: State flows forward, not back to a central point
- **Natural parallelism**: Fan-out/fan-in is a first-class pattern
- **Adaptive workflows**: Agents respond to what they find

What made it work:
- **Explicit result types** (`HandoffResult`): No ambiguity about completion vs handoff
- **Event-driven coordination**: Zero CPU when idle, natural load balancing
- **LLM-based intent routing**: Understanding multi-step intents, not just keyword matching
- **Goal-aware reasoning**: Every agent knows what the user actually wants

The meta-pattern here isn't about agents specifically. It's about designing systems where components understand intent, not just commands. When each part of your system knows *why* it's being asked to do something, it can make better decisions about *how* to do it - and what should happen next.

---

*The code for this project is available on GitHub. Both the V1 orchestrator and V2 autonomous patterns are implemented in the reference codebase.*
