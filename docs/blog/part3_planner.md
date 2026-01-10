# Planning Multi-Agent Workflows: Trading Adaptability for Predictability

*This is Part 3 of a series on building multi-agent systems. [Part 1](part1_architecture.md) covered clean architecture for agents (tools vs services, domain-driven design). [Part 2](part2_autonomous.md) explored autonomous agent coordination (goal-aware reasoning, event-driven handoffs).*

---

In Parts 1 and 2, we explored *who* coordinates multi-agent workflows: a central orchestrator (V1) versus distributed autonomous agents (V2). The autonomous pattern was elegant - agents reasoning about goals and handing off to each other - but it revealed an interesting trade-off.

Every agent in V2 needs to reason about the user's goal. That's a lot of LLM calls:

```
V2 Autonomous Pattern:
  Initial routing: 1 LLM call
  Agent A execution + goal reasoning: 2 LLM calls
  Routing to Agent B: 1 LLM call
  Agent B execution + goal reasoning: 2 LLM calls
  ...

Total for 3-step workflow: ~9 LLM calls
```

When every agent needs to think, you need capable models throughout. That gets expensive.

This led us to explore a different dimension: **What if we front-load the intelligence?**

## In this article, we shall cover:

- Why autonomous agents have high per-step LLM costs
- The economic argument for upfront planning
- How the Planner pattern *enables* strategic model selection
- Implementing DAG-based execution with dependency tracking
- When predictability matters more than adaptability
- Tradeoffs between the three patterns we've explored

---

## The Cost Structure Problem

### V1 Orchestrator Costs

```
Request: "Find videos about Python asyncio, get transcript, summarize"

Orchestrator decides what to do: 1 LLM call (powerful model)
  ↓ delegates to SearchAgent
SearchAgent executes: 1 LLM call (can be cheaper model - just searching)
  ↓ returns to orchestrator
Orchestrator decides next step: 1 LLM call (powerful model)
  ↓ delegates to TranscriptAgent
TranscriptAgent executes: 1 LLM call (can be cheaper model - just fetching)
  ↓ returns to orchestrator
Orchestrator decides final step: 1 LLM call (powerful model)
  ↓ delegates to SummarizeAgent
SummarizeAgent executes: 1 LLM call (needs capable model for summarization)

Total: 6 LLM calls (3 powerful for decisions, 3 mixed for execution)
```

**Cost characteristics:**
- Central decision-making requires powerful model
- Execution can sometimes use cheaper models
- Context accumulates at orchestrator (token costs grow)

### V2 Autonomous Costs

```
Same request: "Find videos about Python asyncio, get transcript, summarize"

Router analyzes intent: 1 LLM call (powerful model)
  ↓ routes to SearchAgent
SearchAgent searches: 1 LLM call (needs capable model)
SearchAgent reasons about goal: 1 LLM call (needs capable model)
  ↓ hands off with intent
Router analyzes new intent: 1 LLM call (powerful model)
  ↓ routes to TranscriptAgent
TranscriptAgent fetches: 1 LLM call (capable model)
TranscriptAgent reasons about goal: 1 LLM call (capable model)
  ↓ hands off with intent
Router analyzes final intent: 1 LLM call (powerful model)
  ↓ routes to SummarizeAgent
SummarizeAgent summarizes: 1 LLM call (capable model needed)
SummarizeAgent reasons about goal: 1 LLM call (capable model)
  ↓ completes

Total: 10 LLM calls (all need capable models for reasoning)
```

**Cost characteristics:**
- Every agent needs to reason about the goal
- Can't easily substitute cheaper models (reasoning quality matters)
- State flows forward (lower context costs than V1)
- Higher per-step costs, but more parallelizable

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

**Cost structure:**
```
Same request: "Find videos about Python asyncio, get transcript, summarize"

Planning: 1 LLM call (powerful model - creates full DAG)

Execution:
  SearchAgent executes "search Python asyncio": 1 call (cheap model OK)
  TranscriptAgent executes "fetch transcript": 1 call (cheap model OK)
  SummarizeAgent executes "summarize key concepts": 1 call (capable model needed)

Total: 4 LLM calls (1 powerful + 2 cheap + 1 capable)
```

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

| Pattern | LLM Calls | Token Usage* | Est. Cost** | Key Characteristic |
|---------|-----------|--------------|-------------|-------------------|
| **V1 Orchestrator** | ~6 | ~5K in / ~2K out | ~$0.04 | Context grows at center |
| **V2 Autonomous** | ~10 | ~8K in / ~3K out | ~$0.06 | Every agent reasons about goal |
| **V3 Planner+DAG** | ~4 | ~3K in / ~1.5K out | ~$0.03 | Single planning call, then execute |

*Token estimates for a "search → transcript → summarize" workflow.*
**Based on GPT-5.2 pricing: $1.75/1M input, $14.00/1M output tokens.*

The cost differences may seem small per-request, but they compound at scale. Processing 10,000 requests daily:
- V1: ~$400/day
- V2: ~$600/day
- V3: ~$300/day

The key insight isn't just raw cost - it's **predictability**. With V3, you know the token budget before execution starts.

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

## Limitations and Tradeoffs

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

See [PLANNER_STATUS_REPORT.md](../PLANNER_STATUS_REPORT.md) for detailed implementation assessment.

---

## Conclusion

The insight that made the Planner pattern compelling wasn't just predictability - it was **economics**.

Autonomous agents (V2) are elegant, but every agent needs to reason about the goal. That means every agent needs a capable model. When you're processing hundreds or thousands of requests, those costs add up.

The Planner pattern lets you be strategic: use a powerful model once to create a complete plan, then execute the plan with reduced per-step overhead. For high-volume scenarios, this can significantly reduce costs compared to autonomous agents.

But it's a tradeoff: you sacrifice the adaptability that makes autonomous agents powerful. The workflow can't change course based on what it finds. If that adaptability matters more than cost, autonomous agents are still the right choice.

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
- **[V2 Autonomous Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_autonomous_agents)** - Covered in Part 2
- **[V3 Planner+DAG Pattern](https://github.com/Chris-hughes10/agents-explore/tree/main/src/youtube_agent_planner)** - This post's focus
- **[Full Source Code](https://github.com/Chris-hughes10/agents-explore)** - Complete implementation with tests
- **[Documentation](https://github.com/Chris-hughes10/agents-explore/tree/main/docs)** - Design philosophy, patterns, and guides

The code is meant to be read and learned from, not just used. Star the repo if you find it useful!
