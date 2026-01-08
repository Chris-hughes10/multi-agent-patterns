# V2: Autonomous Multi-Agent Pattern

## Vision

Build a multi-agent system where agents **self-assign**, **delegate to each other**, and **execute tasks in parallel** without central coordination.

Unlike V1's orchestrator (where a central LLM coordinates every step), V2 agents:
- Claim tasks from a shared queue
- Reason about whether they can complete the goal or need to hand off
- Chain together autonomously, only returning when the full task is done

---

## Current State (January 2026)

### What Works

| Feature | Status | Notes |
|---------|--------|-------|
| Sequential handoff chains | Working | search -> transcript -> summarize |
| Event-driven task queue | Working | Zero CPU when idle |
| Goal-aware agent reasoning | Working | LLM decides complete vs handoff |
| Self-selection (agents claim tasks) | Working | Atomic claim operations |
| Loop detection | Working | Prevents infinite handoff cycles |
| Intent routing | Working | LLM-based routing at handoffs |
| **Parallel task execution** | **Working** | Decentralized fan-out/fan-in via pool |
| **Request analysis** | **Working** | LLM detects parallelism opportunities |

### Architecture (DDD Layout)

```
src/youtube_autonomous_agents/
├── agents/               # Domain layer
│   ├── base.py           # BaseAgent ABC with execute_autonomous()
│   ├── search.py         # SearchAgent
│   ├── transcript.py     # TranscriptAgent
│   ├── summarize.py      # SummarizeAgent
│   ├── writer.py         # WriterAgent
│   └── synthesizer.py    # Entry point + parallelism coordination
├── application/          # Application layer
│   ├── cli.py            # CLI entry point
│   └── main.py           # Shared driver functions
├── infra/                # Infrastructure layer
│   ├── pool.py           # SelfSelectingPool coordination
│   ├── registry.py       # AgentRegistry for discovery
│   ├── task_queue.py     # Event-driven AsyncTaskQueue
│   ├── session.py        # Conversation state + variable resolution
│   ├── intent_router.py  # LLM-based intent routing
│   └── loop_detector.py  # Cycle detection
└── models/               # Shared kernel
    ├── task.py           # Task, TaskResult, TaskStatus
    └── handoff.py        # HandoffResult (complete/handoff/fan_out)
```

---

## Parallel Execution (Implemented)

### How It Works

Parallel execution is **decentralized** - the pool coordinates fan-out/fan-in, not the Synthesizer.
This enables any agent to trigger parallel execution, not just the entry point.

```
User: "Search chuds bbq AND fork and embers for pork loin, summarize"
                              |
                    +---------v---------+
                    |    Synthesizer    |
                    |  _analyze_request |
                    +---------+---------+
                              |
          LLM: "Two channels = parallel searches"
                              |
                    +---------v---------+
                    | pool.submit_fan_  |
                    | out_and_wait()    |
                    +---------+---------+
                              |
         +--------------------+--------------------+
         |                                         |
         v                                         v
    [Task Queue]                            [Task Queue]
    "search chuds bbq"                 "search fork+embers"
         |                                         |
         v                                         v
    SearchAgent claims                     SearchAgent claims
    and executes                           and executes
         |                                         |
         +-----------> TaskGroup <-----------------+
                    (tracks completion)
                              |
                    All tasks complete
                              |
                    +---------v---------+
                    |  Pool posts join  |
                    |  task to queue    |
                    +---------+---------+
                              |
                    +---------v---------+
                    | Continue chain... |
                    +-------------------+
```

### Key Components

**TaskGroup** - Tracks parallel task completion in the pool:
```python
@dataclass
class TaskGroup:
    id: str
    task_ids: list[str]        # IDs of parallel tasks
    join_intent: str           # What to do when all complete
    state: dict[str, Any]      # Shared state for join task
    results: dict[str, Any]    # Collected results
    errors: list[str]          # Any failures

    @property
    def is_complete(self) -> bool:
        return len(self.results) + len(self.errors) >= len(self.task_ids)
```

**HandoffResult.fan_out()** - Action type for parallel execution:
```python
HandoffResult.fan_out(
    intents=["Search chuds bbq for pork loin", "Search fork and embers for pork loin"],
    join_intent="Combine search results and get transcripts",
    state={"query": "pork loin kamado"}
)
```

**SelfSelectingPool.submit_fan_out_and_wait()** - Entry point for parallel execution:
- Creates TaskGroup to track parallel tasks
- Posts each intent as a separate task to the queue
- Waits for all parallel tasks to complete
- Follows the join task chain to completion

**Pool._post_fan_out_tasks()** - Handles fan_out from any agent:
- When an agent returns `HandoffResult.fan_out()`, pool creates parallel tasks
- Each task is routed independently via LLM intent routing
- Results collected in TaskGroup, join posted when complete

**Synthesizer** - Thin entry point:
- Analyzes requests for parallelism via LLM
- Calls `pool.submit_fan_out_and_wait()` or `pool.submit_and_wait()`
- Synthesizes final response for user
- Does NOT coordinate execution - that's the pool's job

### Design Principles

| Principle | Implementation |
|-----------|----------------|
| Decentralized coordination | Pool manages fan-out, not Synthesizer |
| Any agent can parallelize | Return `HandoffResult.fan_out()` from any agent |
| Synthesizer stays thin | Just entry/exit point, delegates to pool |
| LLM reasoning throughout | No keyword matching - LLM detects parallelism |
| Graceful degradation | Partial failures don't stop the whole workflow |

### Robustness Features

**Parallel Task Completion**: Parallel tasks always complete with results (never hand off). This ensures their results are captured in the TaskGroup for the join task. Enabled via `is_parallel_task: True` in state.

**Result Recovery**: If a join task is misrouted, agents can recover parallel results from `state["parallel_results"]`. This prevents data loss from routing errors.

**Video Interleaving**: When combining results from parallel searches, videos are interleaved (A1, B1, A2, B2...) instead of concatenated (A1, A2..., B1, B2...). This ensures diversity when only N videos are selected.

**LLM-Based Video Selection**: TranscriptAgent uses LLM reasoning to select the most relevant videos based on the user's original request (including channel preferences). Configurable via `state["max_transcripts"]` (default: 5).

**LLM-Based Filename Generation**: WriterAgent uses LLM to generate meaningful filenames based on the content topic rather than using generic names.

---

## Sequential Flow (Original)

For requests without parallelism, the original sequential flow applies:

```
User: "Find videos about kamado cooking, get transcripts, summarize"
                              |
                    +---------v---------+
                    |    Synthesizer    |
                    +---------+---------+
                              |
                    +---------v---------+
                    |   SearchAgent     |
                    +---------+---------+
                              |
              "Goal needs transcripts, hand off"
                              |
                    +---------v---------+
                    |  TranscriptAgent  |
                    +---------+---------+
                              |
              "Goal needs summary, hand off"
                              |
                    +---------v---------+
                    |  SummarizeAgent   |
                    +-------------------+
```

---

## Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_v2_autonomous.py | 23 | Agent reasoning, handoffs, chains |
| test_v2_self_selection.py | 10 | Pool coordination, task claiming |
| test_v2_session.py | 24 | Session state, variable resolution |
| test_v2_parallel.py | 16 | Fan-out/fan-in, parallelism detection, pool coordination |
| **Total** | **73** | |

---

## Related Files

- [V2_IMPLEMENTATION_LOG.md](./V2_IMPLEMENTATION_LOG.md) - Historical notes and learnings
- [BLOG_POST_PLAN.md](./BLOG_POST_PLAN.md) - Blog post outline

## Archived Code

The Planner/DAG pattern was separated to `youtube_agent_planner/` for potential future use. It provides upfront execution planning rather than emergent agent coordination.
