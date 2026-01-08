# Next Steps for V2 Implementation

## Current State

**Branch:** `docs/v2-implementation-plan`
**Status:** All 198 tests passing

### Completed Restructure

The codebase has been restructured with clearer naming:

| Module | Description |
|--------|-------------|
| `youtube_agent_orchestrator` | V1 - Orchestrator pattern (conversational) |
| `youtube_autonomous_agents` | V2 - Autonomous pattern (goal-driven) |
| `youtube_agent_planner` | Optional - Planner + DAG execution |

### V2 DDD Architecture

The V2 module now follows Domain-Driven Design:

```
youtube_autonomous_agents/
├── agents/           # Domain layer
│   ├── base.py       # BaseAgent with timeout helpers
│   ├── search.py     # SearchAgent
│   ├── transcript.py # TranscriptAgent
│   ├── summarize.py  # SummarizeAgent
│   ├── writer.py     # WriterAgent
│   └── synthesizer.py # User-facing entry point
├── application/      # Application layer
│   ├── cli.py        # Click CLI commands
│   └── main.py       # Driver functions for programmatic use
├── infra/            # Infrastructure layer
│   ├── pool.py       # SelfSelectingPool coordination
│   ├── registry.py   # AgentRegistry
│   ├── task_queue.py # AsyncTaskQueue
│   ├── session.py    # Session context
│   ├── intent_router.py # LLM-based routing
│   └── loop_detector.py # Circular reference prevention
└── models/           # Shared kernel
    ├── task.py       # Task, TaskResult, TaskStatus
    └── handoff.py    # HandoffResult, OperationTimeout
```

### V1 Application Layer (Refactored)

V1 now follows the same `application/` pattern as V2:

```
youtube_agent_orchestrator/
├── application/      # Application layer
│   ├── cli.py        # Click CLI commands
│   ├── main.py       # Driver functions (process_request, etc.)
│   └── status.py     # Human-friendly status monitoring
├── agents/           # LLM agents
├── tools/            # LLM-callable tools
├── services/         # Business logic
├── models/           # Data structures
└── infra/            # Framework plumbing
```

### CLI Entry Points

```bash
youtube-agent      # V1 Orchestrator
youtube-autonomous # V2 Autonomous
youtube-agent-planner # Planner + DAG
```

---

## Remaining Tasks

### ~~1. CLI Flags for max_transcripts~~ ✅ DONE

Added `--max-transcripts` / `-t` flag to the CLI chat command.

```bash
# Default (5 transcripts)
uv run youtube-agent-v2 chat -r "Find videos about cooking"

# Custom limit
uv run youtube-agent-v2 chat -t 3 -r "Find videos about cooking"
```

**Implementation:** Uses a general `context: dict` parameter pattern that flows through:
- `cli.py` → `main.py` → `synthesizer.py` → pool → agents

### ~~2. V1 Refactor for Consistency~~ ✅ DONE

Refactored V1 to match V2's application layer pattern:
- Renamed `cli/` → `application/`
- Converted argparse to Click
- Split into `cli.py` (commands) + `main.py` (driver functions)

### 3. Blog Post Series

Two-part blog series. Full outline in `docs/BLOG_POST_PLAN.md`.

| Post | Focus | Status |
|------|-------|--------|
| Part 1 | V1 Architecture (Orchestrator) | Outline complete |
| Part 2 | V2 Patterns (Autonomous + Parallel) | Outline needs update |

---

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# V2 specific tests
uv run pytest tests/test_v2_*.py -v

# Quick smoke test
uv run pytest tests/test_v2_autonomous.py -v --tb=short
```

---

## Key Files Reference

| Component | Path |
|-----------|------|
| CLI Entry | `src/youtube_autonomous_agents/application/cli.py` |
| Driver Functions | `src/youtube_autonomous_agents/application/main.py` |
| Synthesizer | `src/youtube_autonomous_agents/agents/synthesizer.py` |
| Pool Coordination | `src/youtube_autonomous_agents/infra/pool.py` |
| BaseAgent | `src/youtube_autonomous_agents/agents/base.py` |
| Blog Plan | `docs/BLOG_POST_PLAN.md` |
| Pattern Docs | `docs/AUTONOMOUS_PATTERN.md` |
