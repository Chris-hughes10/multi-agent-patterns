# Autonomous Agent Pattern

## Overview

The **autonomous pattern** enables agents to reason about goals and hand off to each other via an **event-driven task queue**. Each agent receives the original user goal plus accumulated state, decides what to do, and either completes the task or posts a handoff to the queue for the next agent.

## Key Insight

Every agent thinks. No central coordinator tells them what to do. Handoffs flow through a shared queue.

```
Traditional Orchestrator:
  User → Orchestrator → Agent A → Orchestrator → Agent B → Orchestrator → User

Autonomous Pattern (with event-driven queue):
  User → Queue → Agent A → Queue → Agent B → Queue → Agent C → User
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Request                                │
│   "Find pork loin recipes, get transcripts, summarize, save to md"  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Event-Driven Task Queue                          │
│  • Zero CPU when idle (no polling)                                  │
│  • Agents notified instantly when tasks arrive                      │
│  • Tracks execution path for debugging                              │
│  • Detects loops to prevent infinite handoffs                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │ notify
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
            │ SearchAgent │ │TranscriptAgt│ │SummarizeAgt │ ...
            └─────────────┘ └─────────────┘ └─────────────┘
                    │
                    ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Agent Execution Loop                         │
    │  1. Wait: for queue notification (event-driven)                 │
    │  2. Claim: task if I can handle it (self-selection)             │
    │  3. Execute: do my specialized work                             │
    │  4. Reason: "Is the user's goal satisfied?"                     │
    │  5. Return: complete(result) OR handoff(intent, state)          │
    └─────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            ┌─────────────┐                 ┌─────────────────┐
            │  complete   │                 │     handoff     │
            │  (done!)    │                 │ (post to queue) │
            └─────────────┘                 └─────────────────┘
                                                    │
                                                    ▼
                                    ┌─────────────────────────────────┐
                                    │      New Task Posted to Queue   │
                                    │  Intent + accumulated state     │
                                    │  Next capable agent claims it   │
                                    └─────────────────────────────────┘
                                                    │
                                                    ▼
                                            (cycle continues)
```

## The Four Agents

| Agent | Capability | Input | Output |
|-------|------------|-------|--------|
| **SearchAgent** | `youtube_search` | Search query | List of video results |
| **TranscriptAgent** | `transcript_fetch` | Video IDs | Transcript text + metadata |
| **SummarizeAgent** | `summarization` | Transcripts | Synthesized summary |
| **WriterAgent** | `file_export` | Content to save | Saved file path |

## Example Flow

**User Goal**: "Find pork loin recipes from Chuds BBQ, get transcripts, summarize temps and times, save to notes.md"

```
[Path] search(handoff) → transcript(handoff) → summarize(handoff) → writer(complete)
```

### Step-by-Step Reasoning

1. **SearchAgent** receives goal + empty state
   - Thinks: "Goal needs videos about pork loin recipes"
   - Executes: YouTube search for "Chuds BBQ pork loin"
   - Reasons: "Found videos, but goal also needs transcripts"
   - Returns: `handoff(intent="fetch transcripts", state={videos: [...]})`

2. **TranscriptAgent** receives goal + {videos}
   - Thinks: "I have video IDs, goal needs transcript text"
   - Executes: Fetches transcripts for each video
   - Reasons: "Got transcripts, but goal asks for summarization"
   - Returns: `handoff(intent="summarize content", state={videos, transcripts: [...]})`

3. **SummarizeAgent** receives goal + {videos, transcripts}
   - Thinks: "I have transcripts, goal wants temps/times synthesized"
   - Executes: LLM synthesis across all transcripts
   - Reasons: "Goal asks to save to file"
   - Returns: `handoff(intent="write to file", state={videos, transcripts, summaries: [...]})`

4. **WriterAgent** receives goal + {videos, transcripts, summaries}
   - Thinks: "I have content, goal wants it saved to markdown"
   - Executes: Creates clean markdown, writes to output/
   - Reasons: "File saved, goal is satisfied"
   - Returns: `complete(result="Saved to output/notes.md")`

## Key Components

### HandoffResult Protocol

Agents return one of two result types:

```python
# Goal satisfied - we're done
return HandoffResult.complete(result=my_result)

# Goal not satisfied - pass to next agent
return HandoffResult.handoff(
    intent="natural language description of what's needed next",
    state={**current_state, "my_key": my_result}
)
```

### LLM-Based Goal Reasoning

Each agent uses an LLM to reason about whether the goal is satisfied:

```python
async def _reason_about_goal(self, goal: str, my_output: dict) -> dict:
    prompt = f"""
    USER'S GOAL: "{goal}"
    WHAT I DID: {description_of_my_work}

    Is the goal satisfied, or does it need more work?
    """
    # LLM returns: {"satisfied": bool, "next_step": str}
```

### LLM Intent Router

Routes natural language intents to capable agents:

```python
class LLMIntentRouter:
    async def find_agent_for_intent(self, intent: str, agents: list) -> str:
        prompt = f"""
        INTENT: "{intent}"
        AVAILABLE AGENTS: {agent_capabilities}

        Which agent should handle the FIRST step of this intent?
        """
        # Returns agent name like "transcript" or "summarize"
```

### Loop Detection

Prevents infinite handoff cycles:

```python
# Execution path: search → transcript → search (loop!)
if current_agent in recent_path:
    return PartialResult(error=f"Loop detected: {path}")
```

## Running the Autonomous Pattern

### Command

```bash
uv run youtube-agent-v2 chat
```

The autonomous pattern is the default (and only) pattern in V2.

### With a Single Request

```bash
uv run youtube-agent-v2 chat -r "Find pork loin recipes from Chuds BBQ, get the transcripts, summarize the cooking temps and times, and save to pork_loin_notes.md"
```

### Limit Transcripts Fetched

```bash
# Default fetches up to 5 transcripts
uv run youtube-agent-v2 chat -t 3 -r "Find BBQ videos and summarize them"
```

### Verbose Mode (See Execution Path)

```bash
uv run youtube-agent-v2 -v chat -r "your request here"
```

### Example Output

```
YouTube Agent V2 - Interactive Mode
==================================================
Type 'exit' or 'quit' to stop.

[Autonomous] Starting agent chain...
[Path] search(handoff) → transcript(handoff) → summarize(handoff) → writer(complete)
Saved notes successfully.

## Output file
- **Created:** `output/pork_loin_recipes_20260108.md`
- **Size:** 2611 characters
```

## Parallel Execution

The autonomous pattern supports **parallel fan-out/fan-in** via `HandoffResult.fan_out()`:

```python
# Agent can trigger parallel execution
return HandoffResult.fan_out(
    intents=["Search channel A", "Search channel B"],
    join_intent="Combine results and continue",
    state={"query": "pork loin"}
)
```

**Flow:**
```
User: "Search chuds bbq AND fork and embers for pork loin"
                         │
                         ▼
              ┌──────────────────┐
              │   Synthesizer    │  Analyzes: "Two channels = parallel"
              └────────┬─────────┘
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
          [Continue chain...]
```

**Robustness features:**
- Parallel tasks always complete (never hand off) to ensure results captured
- Results recovered from `state["parallel_results"]` if join is misrouted
- Videos interleaved for diversity when selecting from parallel searches
- LLM selects most relevant videos based on user's channel preferences

See [V2_IMPLEMENTATION_PLAN.md](./V2_IMPLEMENTATION_PLAN.md) for full details.

## When to Use This Pattern

**Good fit:**
- Adaptive workflows where the path isn't known upfront
- Multi-step research tasks that may evolve
- **Parallel searches across multiple sources**
- Building toward truly autonomous systems
- Natural language task descriptions
- Any youtube_autonomous_agents use case (this is the unified pattern)

**Consider alternatives when:**
- Workflow is fixed and predictable → use `youtube-agent-planner` (separate package)
- Need maximum visibility into execution plan → use `youtube-agent-planner`
- Conversational back-and-forth → use V1 orchestrator (`youtube-agent`)

## Comparison with Other Approaches

| Aspect | Orchestrator (V1) | Planner + DAG | V2 Autonomous |
|--------|-------------------|---------------|---------------|
| **Control** | LLM decides each step | LLM plans upfront | Agents decide locally |
| **Queue** | None | None | Event-driven self-selection |
| **LLM Calls** | N (per step) | 1 planning + N execution | 2N (routing + reasoning) |
| **Adaptability** | High (conversational) | Re-plan on failure | Continuous |
| **Debuggability** | Medium | Very high (inspect DAG) | Medium (execution path) |
| **Best for** | Conversational apps | Complex known workflows | Goal-driven batch tasks |
| **Command** | `youtube-agent` | `youtube-agent-planner` | `youtube-agent-v2` |

## File Locations

| Component | Path |
|-----------|------|
| Self-Selection Pool | `src/youtube_autonomous_agents/infra/pool.py` |
| Task Queue | `src/youtube_autonomous_agents/infra/task_queue.py` |
| Intent Router | `src/youtube_autonomous_agents/infra/intent_router.py` |
| Base Agent | `src/youtube_autonomous_agents/agents/base.py` |
| Handoff Models | `src/youtube_autonomous_agents/models/handoff.py` |
| Agents | `src/youtube_autonomous_agents/agents/` |
| CLI Entry | `src/youtube_autonomous_agents/application/cli.py` |
| Driver Functions | `src/youtube_autonomous_agents/application/main.py` |
