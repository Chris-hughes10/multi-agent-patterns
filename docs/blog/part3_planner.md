# Planning Multi-Agent Workflows: Trading Adaptability for Predictability

*This is Part 3 of a series on building multi-agent systems. [Part 1](part1_architecture.md) covered clean architecture for agents (tools vs services, domain-driven design). [Part 2](part2_autonomous.md) explored autonomous agent coordination (goal-aware reasoning, event-driven handoffs).*

---

In Parts 1 and 2, we explored *who* coordinates multi-agent workflows: a central orchestrator (V1) versus distributed autonomous agents (V2). The autonomous pattern was elegant - agents reasoning about goals and handing off to each other - but it revealed an interesting trade-off.

Every agent in V2 needs to reason about the user's goal. In our benchmark workflow ("search → fetch transcripts → summarize → write"), this adds up:

```
V2 Autonomous Pattern (actual benchmark):
  Dispatcher routing (4 handoffs):    4 LLM calls
  Agent validation (4 agents):        4 LLM calls
  Agent execution reasoning:          3 LLM calls

Total: 11 LLM calls (zero variance across runs)
```

When every agent needs to think, you need capable models throughout. That gets expensive.

This led us to explore a different dimension: **What if we front-load the intelligence?**

## In this article, we shall cover:

- Why autonomous agents have high per-step LLM costs
- The economic argument for upfront planning
- How the Planner pattern *enables* strategic model selection
- Implementing DAG-based execution with dependency tracking
- When predictability matters more than adaptability
- Trade-offs between the three patterns we've explored

---

## The Cost Structure Problem

### V1 Orchestrator Costs (actual benchmark: 17-34 calls)

The orchestrator pattern shows **high variance** because the LLM decides the workflow at runtime:

```
V1 Orchestrator Pattern (Run A - 17 calls, minimal approach):
  Orchestrator: "I'll search both channels"        → 2 SearchAgent calls
  Orchestrator: "Now fetch transcripts"            → 3 TranscriptAgent calls
  Orchestrator: "Writer can synthesize directly"   → 1 WriterAgent call
  Plus orchestrator decision overhead:             ~11 LLM calls

V1 Orchestrator Pattern (Run B - 34 calls, thorough approach):
  Orchestrator: "I'll do three targeted searches"  → 3 SearchAgent calls
  Orchestrator: "Fetch all transcripts"            → 5 TranscriptAgent calls
  Orchestrator: "Summarize each, then combine"     → 4 SummarizeAgent calls
  Orchestrator: "Write the final document"         → 1 WriterAgent call
  Plus orchestrator decision overhead:             ~21 LLM calls
```

Same request, different runtime decisions, 2× cost difference.

**Cost characteristics:**
- Orchestrator decides *scope* at runtime (how many searches? skip summarization?)
- Each decision point is an LLM call
- Context accumulates at orchestrator (token costs grow with chain length)
- **Unpredictable costs** - you don't know until it runs

### V2 Autonomous Costs (actual benchmark: 11 calls, zero variance)

```
V2 Autonomous Pattern (consistent across all runs):
  Dispatcher routing (4 handoffs):    4 LLM calls
  Agent validation (4 agents):        4 LLM calls
  Agent execution reasoning:          3 LLM calls

Total: 11 LLM calls (zero variance across runs)
```

**Cost characteristics:**
- Centralized dispatcher routes tasks (1 LLM call per handoff)
- Agents validate assignments (1 LLM call per agent)
- Execution uses direct service calls where possible
- **Predictable costs** - 11 calls for every request

### The Economic Insight

The Planner pattern opens an architectural opportunity:

1. Use a powerful model ONCE to create a complete plan
2. Execute the plan mechanically (potentially with cheaper/faster models)
3. Trade adaptability for predictable costs

This is the **Planner + DAG pattern**. The core benefit is *reduced redundant reasoning* - instead of every agent re-evaluating "is the goal satisfied?", you decide the workflow once upfront.

> **Note on model tiers**: While the pattern *enables* using different model tiers for planning vs execution, our reference implementation uses consistent model quality throughout. The architectural benefit is immediate (inspectable plans, reduced reasoning overhead); model tier optimization is a straightforward enhancement the pattern supports.

---

## The Planner Pattern: Decide Everything Upfront

### Core Idea

```
User Request
    ↓
Planner (powerful model): "What's the complete workflow?"
    ↓
ExecutionDAG (data structure - no LLM needed)
    ↓
Step 1 → Agent A (cheaper model - just execute)
Step 2 → Agent B (cheaper model - just execute)
Step 3 → Agent C (capable model if needed for task complexity)
```

**Cost structure (actual benchmark: 3 calls, zero variance):**
```
V3 Planner Pattern (consistent across all runs):
  PlannerAgent creates DAG:           1 LLM call
  Search execution:                   0 LLM calls (direct YouTube API call)
  Transcript fetching:                0 LLM calls (direct service call)
  Summarization × 2:                  2 LLM calls (requires reasoning)
  File writing:                       0 LLM calls (direct file I/O)

Total: 3 LLM calls (zero variance across runs)
```

**Why so efficient?** The key insight is that most workflow steps don't need LLM reasoning:
- **Search**: Just call the YouTube API with parameters from the plan
- **Transcript**: Just fetch from YouTube's transcript service
- **File writing**: Just write the formatted output to disk

Only **summarization** requires an LLM to reason about content. Everything else is mechanical execution of the plan. This is why V3 uses 80% fewer LLM calls than V2.

### What You Get

**1. Cost Control**
- Know exact number of steps before starting
- Use model tiers strategically (powerful for planning, cheaper for execution)
- No per-step reasoning overhead

**2. Inspectable Plans**
```json
{
  "goal": "Find asyncio videos, get transcript, summarize",
  "steps": [
    {
      "id": "search_asyncio",
      "agent": "search",
      "model_tier": "cheap",
      "input": {"query": "Python asyncio tutorial"}
    },
    {
      "id": "fetch_transcript",
      "agent": "transcript",
      "model_tier": "cheap",
      "input": {"video_id": "$search_asyncio.results[0].id"},
      "depends_on": ["search_asyncio"]
    },
    {
      "id": "summarize",
      "agent": "summarize",
      "model_tier": "capable",
      "input": {"text": "$fetch_transcript.text"},
      "depends_on": ["fetch_transcript"]
    }
  ]
}
```

You can SEE this before anything runs. Validate it. Store it. Modify it.

**3. Compliance & Auditability**
- "Show me what will happen before you do it"
- Compare planned steps vs actual execution
- Clear dependency chain for debugging

**4. Parallel Execution**
Independent steps (no shared dependencies) run concurrently:
```
Step 1a and 1b (no dependencies) → execute in parallel
Step 2 (depends on both 1a and 1b) → waits for completion
```

### What You Sacrifice

**1. Adaptability**
- Can't change course based on findings
- If search returns no relevant videos, plan still tries to fetch transcripts
- Mitigation: Re-plan on failure (adds planning cost)

**2. Upfront Planning Cost**
- Every request pays planning cost, even simple ones
- V1/V2 only use LLM when needed at each step

**3. Plan Quality Dependency**
- If planner generates invalid DAG, validation catches it but requires re-planning
- Planner might hallucinate non-existent agents or capabilities

---

## Implementation: The DAG Executor

### ExecutionDAG Structure

```python
@dataclass
class DAGStep:
    id: str                           # Unique identifier
    agent_name: str                   # Which agent executes
    description: str                  # Human-readable intent
    input_template: dict[str, Any]    # Input (may have $variables)
    depends_on: list[str]             # Steps that must complete first
    model_tier: str                   # "powerful" | "capable" | "cheap"
    status: StepStatus                # pending/ready/running/completed/failed
    result: Any = None                # Output after execution

@dataclass
class ExecutionDAG:
    goal: str                         # User's original goal
    steps: list[DAGStep]              # Ordered workflow

    def get_ready_steps(self, completed: set[str]) -> list[DAGStep]:
        """Get steps whose dependencies are satisfied."""
        return [
            step for step in self.steps
            if step.status == "pending"
            and all(dep in completed for dep in step.depends_on)
        ]

    def validate(self) -> list[str]:
        """Check for cycles, missing deps, duplicate IDs."""
        # Topological sort to detect cycles
        # Verify all depends_on references exist
        # Check for duplicate step IDs
```

### The Execution Loop

```python
async def execute_dag(dag: ExecutionDAG, agents: dict) -> dict:
    """Execute DAG with dependency tracking and parallelism."""

    completed = set()
    results = {}

    while len(completed) < len(dag.steps):
        # Get all steps whose dependencies are satisfied
        ready_steps = dag.get_ready_steps(completed)

        if not ready_steps:
            if len(completed) == len(dag.steps):
                break  # All done
            else:
                raise ExecutionError("Deadlock: no ready steps but workflow incomplete")

        # Execute ready steps in parallel
        tasks = [
            execute_step(step, agents[step.agent_name], results)
            for step in ready_steps
        ]

        step_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for step, result in zip(ready_steps, step_results):
            if isinstance(result, Exception):
                # Handle failure (could trigger re-planning)
                step.status = "failed"
                raise ExecutionError(f"Step {step.id} failed: {result}")
            else:
                step.status = "completed"
                completed.add(step.id)
                results[step.id] = result

    return results
```

### Variable Resolution

Steps reference outputs from previous steps using `$step_id.field` syntax:

```python
def resolve_variables(input_template: dict, results: dict) -> dict:
    """Resolve $step_id.field references to actual values."""

    resolved = {}
    for key, value in input_template.items():
        if isinstance(value, str) and value.startswith("$"):
            # Parse $step_id.field.nested
            parts = value[1:].split(".")
            step_id = parts[0]

            # Navigate nested fields
            result = results[step_id]
            for part in parts[1:]:
                if "[" in part:  # Array access: results[0]
                    field, idx = part.split("[")
                    idx = int(idx.rstrip("]"))
                    result = result[field][idx]
                else:
                    result = result[part]

            resolved[key] = result
        else:
            resolved[key] = value

    return resolved
```

**Example:**
```python
# Step input template
{"video_id": "$search_asyncio.results[0].id"}

# Results from search_asyncio step
results["search_asyncio"] = {
    "results": [
        {"id": "abc123", "title": "Python Asyncio Tutorial"},
        {"id": "def456", "title": "Advanced Asyncio"}
    ]
}

# Resolves to
{"video_id": "abc123"}
```

### Model Tier Strategy (Architectural Pattern)

The DAG structure enables a powerful optimization: assign different model tiers based on task complexity. Here's what this *could* look like:

```python
def get_model_for_tier(tier: str) -> str:
    """Map model tiers to actual model names."""
    return {
        "powerful": "gpt-4",           # Planning, complex reasoning
        "capable": "gpt-4o-mini",      # General execution
        "cheap": "gpt-3.5-turbo",      # Simple execution tasks
    }[tier]

async def execute_step(step: DAGStep, agent: BaseAgent, results: dict) -> Any:
    """Execute a single DAG step with appropriate model tier."""

    # Resolve variable references
    input_data = resolve_variables(step.input_template, results)

    # Get model for this step's tier
    model = get_model_for_tier(step.model_tier)

    # Execute agent with resolved input (no goal reasoning needed)
    result = await agent.execute_direct(
        input_data=input_data,
        model=model
    )

    return result
```

While our reference implementation doesn't implement model tier selection (all agents use the same model), the pattern makes this optimization straightforward to add. The key insight is that once you have an explicit plan, you can make informed decisions about resource allocation per step.

---

## Comparison: Three Patterns

### Cost Analysis

| Pattern | LLM Calls* | Variance | Why |
|---------|-----------|----------|-----|
| **V1 Orchestrator** | 17-34 | **High** | LLM decides workflow at runtime - unpredictable |
| **V2 Autonomous** | 11 | **None** | Dispatcher routes + agents validate, then execute via direct service calls |
| **V3 Planner+DAG** | ~3 | **None** | Single planning call, then mechanical execution via direct service calls |

*Measured LLM calls for a "search → fetch transcripts → summarize → write" workflow using the reference implementation. Numbers are based on multiple benchmark runs.*

The key insight here is **predictability, not just efficiency**.

**V1 Orchestrator breakdown (17-34 calls):**
The orchestrator makes LLM calls at each decision point, plus each sub-agent makes its own calls. The variance comes from runtime decisions:

| Decision Point | Observed Variance |
|----------------|-------------------|
| Search strategy | 1-3 searches, sequential or parallel |
| Step skipping | Summarization sometimes skipped entirely |
| Delegation phrasing | Different wording affects sub-agent behaviour |

With verbose logging enabled (`-v` flag), we can see these decisions in action:

```
# Run A (17 calls) - Minimal approach, skips summarization
SearchAgent called with: Kamado pork loin Fork and Embers
SearchAgent called with: Chuds BBQ pork loin kamado
TranscriptAgent called with: Fetch transcript for video FsbwQI-EI-k...
TranscriptAgent called with: Fetch transcript for video 2AF1ysZ8eEA...
TranscriptAgent called with: Fetch transcript for video fI86yXKlnQA...
WriterAgent called with: Write a markdown file...  # No SummarizeAgent!

# Run B (25 calls) - Thorough approach with summarization
SearchAgent called with: Find YouTube videos where Fork and Embers...
SearchAgent called with: Find YouTube videos where Chuds BBQ...
SearchAgent called with: Find top YouTube videos about cooking pork loin...
TranscriptAgent called with: ...
SummarizeAgent called with: From the provided transcripts, extract...
WriterAgent called with: ...
```

Run A decided the WriterAgent could synthesize directly from transcripts. Run B added a summarization step. Both produced valid outputs, but with different costs.

**V2 Autonomous breakdown (11 calls, consistent):**
The dispatcher pattern centralizes routing decisions:
- Dispatcher routing: 4 calls (one per handoff in the chain)
- Agent validation: 4 calls (each agent confirms assignment)
- Execution reasoning: 3 calls (goal reasoning where needed)

In benchmark testing, V2 produced **exactly 11 calls across all runs with zero variance**. Why? The dispatcher routes each task to a specific agent (1 LLM call), the agent validates the assignment (1 LLM call), then executes using direct service calls where possible. Only steps requiring actual reasoning (like summarization) use additional LLM calls during execution.

**V3 Planner breakdown (~3 calls):**
- PlannerAgent: 1 call (creates the complete DAG upfront)
- Summarization: 2 calls (only step requiring LLM reasoning)
- All other execution: 0 LLM calls (direct service calls)

Search, transcript fetching, and file writing are executed mechanically via direct service calls - no LLM reasoning needed. Only summarization requires LLM involvement during execution. This is why V3 is dramatically more efficient: it front-loads all reasoning into the planning phase.

### When to Use Each Pattern

| Question | Best Pattern | Rationale |
|----------|--------------|-----------|
| Building a conversational interface? | **V1 Orchestrator** | Back-and-forth, context maintenance |
| Need agents to adapt to findings? | **V2 Autonomous** | Goal-aware reasoning, emergent workflows |
| Running high-volume batch processing? | **V3 Planner+DAG** | Lowest per-request cost |
| Need to approve workflows before execution? | **V3 Planner+DAG** | Inspectable plans |
| Compliance/audit requirements? | **V3 Planner+DAG** | Full execution trace |
| Complex dependencies between steps? | **V3 Planner+DAG** | Explicit DAG prevents mistakes |
| Debugging complex workflows? | **V3 Planner+DAG** | Compare plan vs execution |
| Cost is primary constraint? | **V3 Planner+DAG** | Strategic model tier usage |
| Adaptability is primary constraint? | **V2 Autonomous** | Responds to what it finds |
| Simplicity is primary constraint? | **V1 Orchestrator** | Well-understood pattern |

### Quick Decision Tree

```
┌─────────────────────────────────────────────────────────────┐
│         Which Multi-Agent Pattern Should You Use?           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Do you need conversational    │
              │ back-and-forth with the user? │
              └───────────────────────────────┘
                     │              │
                    YES             NO
                     │              │
                     ▼              ▼
              ┌──────────┐   ┌─────────────────────────────┐
              │    V1    │   │ Do agents need to adapt     │
              │Orchestrator│  │ based on what they find?    │
              └──────────┘   └─────────────────────────────┘
                                    │              │
                                   YES             NO
                                    │              │
                                    ▼              ▼
                             ┌──────────┐   ┌─────────────────────┐
                             │    V2    │   │ Do you need to      │
                             │Autonomous│   │ inspect/approve the │
                             └──────────┘   │ plan before running?│
                                            └─────────────────────┘
                                                   │         │
                                                  YES        NO
                                                   │         │
                                                   ▼         ▼
                                            ┌──────────┐  ┌──────────┐
                                            │    V3    │  │ Start    │
                                            │ Planner  │  │ with V1  │
                                            │  + DAG   │  │(simplest)│
                                            └──────────┘  └──────────┘
```

**The short version:**
- **V1 Orchestrator**: Start here. Simple, conversational, well-understood.
- **V2 Autonomous**: When workflows should emerge from agent reasoning.
- **V3 Planner+DAG**: When you need predictability, auditability, or cost control.

### Design Space Summary

We've now explored multi-agent coordination across three dimensions:

**1. Architecture (Part 1):** How to structure clean agent code
- Tools vs Services separation
- Domain-Driven Design for agent systems
- Strategic testing with minimal mocking

**2. Who Coordinates (Part 2):** Central vs distributed
- V1: Central orchestrator directs everything
- V2: Distributed agents self-coordinate

**3. When to Decide (Part 3):** Runtime vs upfront
- V1/V2: Decide at each step (adaptive)
- V3: Decide everything upfront (predictable)

---

## Limitations and Trade-offs

### What Planner+DAG Can't Do Well

**1. Handle Unexpected Conditions**
```
Plan: Search → Fetch Transcript → Summarize

Reality: Search returns no relevant videos
Problem: Plan still tries to fetch transcript for non-existent video

Mitigation: Error handling + re-planning (adds cost)
```

**2. Conversational Workflows**
- User wants to refine based on intermediate results
- V1 orchestrator maintains conversation context naturally
- V3 would need to re-plan for each user input

**3. Exploratory Research**
- "Find interesting videos about X" (undefined criteria)
- V2 autonomous agents can explore and adapt
- V3 needs concrete plan upfront

### When Runtime Decisions Win

- User needs evolve during conversation
- Workflow depends on quality of intermediate findings
- Cost sensitivity when many requests don't need full workflow
- Unknown complexity until you start

### When Upfront Planning Wins

- High-volume processing (cost matters more than adaptability per request)
- Compliance requires pre-approval of execution plan
- Complex dependencies easy to get wrong manually
- Need to estimate cost/time before starting
- Debugging is critical (plan as reference for "what should have happened")

---

## Hybrid Approaches

### Adaptive Planning

Best of both worlds: plan high-level structure, re-plan on surprises.

```python
async def adaptive_execution(user_goal: str) -> Any:
    """Execute with planning but adapt when needed."""

    # Create initial plan
    plan = await planner.create_plan(user_goal, model="powerful")

    for step in plan.steps:
        try:
            # Execute step with cheap model
            result = await execute_step(step, model="cheap")

            # Validate result quality
            if not is_acceptable(result, user_goal):
                # Re-plan remainder with new context
                remaining_plan = await planner.replan(
                    original_goal=user_goal,
                    completed_steps=completed,
                    issue=f"Step {step.id} produced inadequate result",
                    model="powerful"
                )
                plan = merge_plans(completed, remaining_plan)

        except ExecutionError as e:
            # Execution failed - re-plan
            plan = await planner.replan(
                original_goal=user_goal,
                completed_steps=completed,
                failure=str(e),
                model="powerful"
            )
```

**Cost characteristics:**
- Start with single planning call (optimistic)
- Add re-planning only when needed (failures, quality issues)
- Still uses cheap models for most execution

### Tiered Model Selection

```python
# Define model requirements per agent
AGENT_MODEL_REQUIREMENTS = {
    "search": "cheap",        # Simple YouTube search
    "transcript": "cheap",    # Mechanical transcript fetch
    "summarize": "capable",   # Needs understanding
    "writer": "cheap",        # Template-based file writing
    "synthesize": "powerful", # Complex reasoning across sources
}

# Planner respects these when assigning model tiers
def assign_model_tier(step: DAGStep) -> str:
    """Assign model tier based on agent requirements."""
    return AGENT_MODEL_REQUIREMENTS[step.agent_name]
```

---

## Implementation Status

The Planner+DAG pattern is implemented in `youtube_agent_planner/` as a separate package.

**Current state:** ✅ Fully functional - all tests pass (31/31), CLI works

**What's implemented:**
- ✅ PlannerAgent creates execution DAGs from natural language
- ✅ DAGExecutor runs plans with dependency tracking
- ✅ Parallel execution of independent steps
- ✅ Variable resolution ($step_id.field syntax)
- ✅ Plan validation (cycles, missing deps, invalid agents)
- ✅ Error handling with PartialResult

**What's aspirational** (discussed in this post but not yet implemented):
- 🟡 Model tier selection (powerful for planning, cheap for execution)
  - Architecture supports it, just needs configuration
- 🟡 Re-planning on failure (stubbed in code, needs wiring)

**Note**: The economic argument for the Planner pattern is sound - upfront planning *does* reduce redundant LLM reasoning. However, the specific optimization of using different model tiers per step is an enhancement the pattern enables rather than a current feature. The core value is inspectable plans and predictable execution flow.

---

## Conclusion

The insight that made the Planner pattern compelling wasn't just predictability - it was **economics**.

Autonomous agents (V2) are elegant, but every agent needs to reason about the goal. That means every agent needs a capable model. When you're processing hundreds or thousands of requests, those costs add up.

The Planner pattern lets you be strategic: use a powerful model once to create a complete plan, then execute the plan with reduced per-step overhead. For high-volume scenarios, this can significantly reduce costs compared to autonomous agents.

But it's a trade-off: you sacrifice the adaptability that makes autonomous agents powerful. The workflow can't change course based on what it finds. If that adaptability matters more than cost, autonomous agents are still the right choice.

**The Three Patterns, Summarized:**

- **V1 Orchestrator:** Simple, conversational, well-understood
- **V2 Autonomous:** Adaptive, emergent, goal-aware
- **V3 Planner+DAG:** Predictable, economical, auditable

Choose based on your constraints: cost, adaptability, compliance, simplicity.

---

**What's Next:** This completes our exploration of multi-agent coordination patterns. All three implementations are available in the reference codebase. Try them, break them, adapt them to your needs.

The patterns aren't mutually exclusive. Real systems might use:
- V1 for user-facing conversational interfaces
- V3 for backend batch processing
- V2 for exploratory research workflows

Multi-agent systems aren't mysterious. They're software systems with clear architectural choices. Choose the pattern that fits your constraints.

---

## View the Code

All patterns described in this series are implemented in the reference codebase:

- **[V1 Orchestrator Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_agent_orchestrator)** - Covered in Part 1
- **[V2 Autonomous Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_goal_agents)** - Covered in Part 2
- **[V3 Planner+DAG Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_agent_planner)** - This post's focus
- **[Full Source Code](https://github.com/Chris-hughes10/agents-explore)** - Complete implementation with tests
- **[Documentation](https://github.com/Chris-hughes10/agents-explore/tree/main/docs)** - Design philosophy, patterns, and guides

The code is meant to be read and learned from, not just used. Star the repo if you find it useful!
