# Planner + DAG Pattern

> **Note**: This pattern is available as a separate package: `youtube-agent-planner`

## Overview

The **planner pattern** uses an LLM to analyze the user's request upfront and create a structured execution plan (DAG - Directed Acyclic Graph). The DAGExecutor then runs the plan with dependency tracking and parallel execution of independent steps.

This pattern is **decoupled from youtube_autonomous_agents** to keep each approach focused:
- `youtube-agent-v2` - Autonomous agents with event-driven self-selection
- `youtube-agent-planner` - Explicit planning with DAG execution

## Key Insight

The plan is **inspectable data**, not implicit LLM reasoning. You can see exactly what will happen before it runs.

```
Traditional Orchestrator:
  User → LLM decides step 1 → LLM decides step 2 → ... (opaque)

Planner + DAG:
  User → LLM creates full plan → Inspect plan → Execute mechanically
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Request                                │
│     "Find a video about Python asyncio, get transcript, summarize"  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         PlannerAgent                                │
│  • Analyzes user request                                            │
│  • Discovers available agents from registry                         │
│  • Creates DAG with steps, dependencies, variable references        │
│  • Validates agent names exist                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ExecutionDAG                                 │
│  {                                                                  │
│    "goal": "Find asyncio video, get transcript, summarize",         │
│    "steps": [                                                       │
│      { "id": "yt_search", "agent": "search", ... },                 │
│      { "id": "fetch_transcript", "agent": "transcript",             │
│        "depends_on": ["yt_search"], ... },                          │
│      { "id": "summarize_key_points", "agent": "summarize",          │
│        "depends_on": ["fetch_transcript"], ... }                    │
│    ]                                                                │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         DAGExecutor                                 │
│  • Validates DAG structure (no cycles, valid dependencies)          │
│  • Finds ready steps (dependencies satisfied)                       │
│  • Executes ready steps in parallel                                 │
│  • Resolves variable references ($step_id.field)                    │
│  • Stores results in Session for later steps                        │
│  • Handles failures with optional re-planning                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
    ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
    │   Step 1    │         │   Step 2    │         │   Step 3    │
    │  (search)   │ ──────► │ (transcript)│ ──────► │ (summarize) │
    │  parallel   │         │  after: 1   │         │  after: 2   │
    └─────────────┘         └─────────────┘         └─────────────┘
```

## Example DAG

For the request: "Find a YouTube video about Python asyncio basics, get its transcript, and summarize the key points"

```json
{
  "goal": "Find asyncio video, get transcript, summarize key points",
  "steps": [
    {
      "id": "yt_search_asyncio",
      "agent": "search",
      "description": "Search YouTube for Python asyncio basics tutorial",
      "input": {"query": "Python asyncio basics tutorial"},
      "depends_on": []
    },
    {
      "id": "fetch_transcript",
      "agent": "transcript",
      "description": "Get transcript from the first search result",
      "input": {"video_id": "$yt_search_asyncio.results[0].video_id"},
      "depends_on": ["yt_search_asyncio"]
    },
    {
      "id": "summarize_key_points",
      "agent": "summarize",
      "description": "Summarize the key asyncio concepts from the transcript",
      "input": {
        "text": "$fetch_transcript.text",
        "title": "$fetch_transcript.title"
      },
      "depends_on": ["fetch_transcript"]
    }
  ]
}
```

## Key Components

### DAGStep

Each step in the execution plan:

```python
@dataclass
class DAGStep:
    id: str                           # Unique identifier
    agent_name: str                   # Which agent executes this
    description: str                  # Human-readable description
    input_template: dict[str, Any]    # Input data (may have $variables)
    depends_on: list[str]             # Step IDs that must complete first
    status: StepStatus                # pending/ready/running/completed/failed
    result: Any                       # Output after execution
```

### ExecutionDAG

The full execution plan:

```python
@dataclass
class ExecutionDAG:
    goal: str                         # User's goal
    steps: list[DAGStep]              # Ordered list of steps

    def get_ready_steps(self, completed: set[str]) -> list[DAGStep]:
        """Get steps whose dependencies are satisfied."""

    def validate(self) -> list[str]:
        """Check for cycles, missing deps, duplicate IDs."""
```

### Variable Resolution

Steps can reference outputs from previous steps using `$step_id.field` syntax:

| Syntax | Meaning |
|--------|---------|
| `$search` | Full result from "search" step |
| `$search.results` | The "results" field from search output |
| `$search.results[0]` | First item in results array |
| `$search.results[0].video_id` | video_id from first result |

The DAGExecutor resolves these variables at runtime using the Session:

```python
def _resolve_variables(self, template: Any) -> Any:
    if template.startswith("$"):
        return self._session.resolve(template)  # e.g., "$search.results[0].video_id"
```

### PlannerAgent

Creates the DAG from user requests:

```python
class PlannerAgent:
    async def create_plan(self, user_request: str) -> ExecutionDAG:
        """Use LLM to analyze request and create execution plan."""

    async def replan(self, original_goal, completed_results, failed_step, error) -> ExecutionDAG:
        """Create revised plan after a failure."""
```

The planner prompt includes:
- Available agents and their capabilities
- Valid agent names (enforced during parsing)
- Variable reference syntax
- Example DAG format

### DAGExecutor

Runs the DAG with parallel execution:

```python
class DAGExecutor:
    async def execute(self, dag: ExecutionDAG) -> dict[str, Any] | PartialResult:
        """Execute DAG with dependency tracking."""

    async def _execute_dag(self, dag: ExecutionDAG) -> None:
        while not dag.is_complete():
            ready_steps = dag.get_ready_steps(self._completed_steps)
            # Execute ready steps in parallel
            await asyncio.gather(*[self._execute_step(s) for s in ready_steps])
```

## Running the Planner Pattern

### Command

```bash
uv run youtube-agent-planner chat
```

### With a Single Request

```bash
uv run youtube-agent-planner chat -r "Find a YouTube video about Python asyncio basics, get its transcript, and summarize the key points"
```

### Verbose Mode

```bash
uv run youtube-agent-planner -v chat -r "your request here"
```

### Example Output

```
YouTube Agent Planner - Interactive Mode
==================================================
Type 'exit' or 'quit' to stop.

[Planning...] Creating execution plan ✓ (3 steps)
[Plan] Goal: Find asyncio video, get transcript, summarize key points
  → yt_search_asyncio: Search YouTube for Python asyncio basics tutorial
  → fetch_transcript: Get transcript from first result (after: yt_search_asyncio)
  → summarize_key_points: Summarize key concepts (after: fetch_transcript)
[Executing...] Running DAG

## Key Points Summary

**What is asyncio?**
- Python's built-in library for writing concurrent code...
```

## Parallel Execution

Independent steps run in parallel:

```
Example DAG:
  search_video_a ──────────────────────────┐
                                           ├──► combine_results
  search_video_b ──────────────────────────┘

Execution:
  [t=0] search_video_a starts
  [t=0] search_video_b starts (parallel!)
  [t=1] search_video_a completes
  [t=2] search_video_b completes
  [t=2] combine_results starts (both deps satisfied)
```

## Re-planning on Failure

When a step fails, the planner can create a revised plan:

```
Original plan: search → transcript → summarize
                              ↓
                         FAILED (video unavailable)
                              ↓
Re-plan: search → get different video → transcript → summarize
```

```python
executor = DAGExecutor(
    registry=registry,
    session=session,
    planner=planner_agent,    # Enable re-planning
    max_replans=3,            # Max retry attempts
)
```

## Agent Validation

The planner validates that all step agents exist:

```python
# In PlannerAgent._parse_dag_response()
valid_agent_names = {a.name for a in self._registry.all_agents()}
for step in data["steps"]:
    agent_name = step.get("agent")
    if agent_name not in valid_agent_names:
        raise ValueError(f"Invalid agent '{agent_name}'")
```

This prevents the LLM from inventing agents like "extract_parameters" or "filter_results".

## When to Use This Pattern

**Good fit:**
- Complex multi-step workflows
- Need visibility into execution plan before running
- Independent steps that can run in parallel
- Want to inspect/modify plans programmatically
- Need re-planning capability on failures

**Consider alternatives when:**
- Workflow is unknown upfront → use `youtube-agent-v2` (autonomous)
- Need continuous adaptation → use `youtube-agent-v2` (autonomous)
- Conversational back-and-forth → use `youtube-agent` (V1 orchestrator)

## Comparison with Other Approaches

| Aspect | Orchestrator (V1) | Planner + DAG | V2 Autonomous |
|--------|-------------------|---------------|---------------|
| **Planning** | None (step-by-step) | Upfront (full plan) | None (emergent) |
| **Visibility** | Low | Very high (inspect DAG) | Medium (execution path) |
| **Parallelism** | None | Yes (independent steps) | Via queue |
| **LLM Calls** | N (per step) | 1 planning + N execution | 2N (routing + reasoning) |
| **Adaptability** | High | Re-plan on failure | Continuous |
| **Best for** | Conversational apps | Complex known workflows | Goal-driven batch tasks |
| **Command** | `youtube-agent` | `youtube-agent-planner` | `youtube-agent-v2` |

## File Locations

| Component | Path |
|-----------|------|
| PlannerAgent | `src/youtube_agent_planner/agents/planner.py` |
| DAGExecutor | `src/youtube_agent_planner/infra/dag_executor.py` |
| ExecutionDAG | `src/youtube_agent_planner/infra/dag_executor.py` |
| DAGStep | `src/youtube_agent_planner/infra/dag_executor.py` |
| Session | `src/youtube_autonomous_agents/infra/session.py` (shared) |
| CLI Entry | `src/youtube_agent_planner/cli/commands.py` |

## Creating Plans Programmatically

For testing or known workflows, you can create plans without the LLM:

```python
from youtube_agent_planner.agents.planner import PlannerAgent

planner = PlannerAgent(registry=registry)

dag = planner.create_simple_plan(
    goal="Fetch and summarize a specific video",
    steps=[
        {
            "id": "fetch",
            "agent": "transcript",
            "description": "Get transcript",
            "input": {"video_id": "abc123"},
            "depends_on": []
        },
        {
            "id": "summarize",
            "agent": "summarize",
            "description": "Summarize transcript",
            "input": {"text": "$fetch.text"},
            "depends_on": ["fetch"]
        }
    ]
)
```
