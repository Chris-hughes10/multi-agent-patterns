# Next Steps for V2 Implementation

## Current State

**Branch:** `docs/v2-implementation-plan`
**Latest commit:** `387a20e` - "Implement V2 parallel execution with LLM-based robustness features"
**Status:** All tests passing (48 tests across autonomous, self-selection, and parallel test files)

The V2 autonomous multi-agent system is feature-complete with:
- Decentralized parallel execution (fan-out/fan-in)
- LLM-based video selection and filename generation
- Robustness features (result recovery, video interleaving)
- Updated documentation

---

## Task 1: Cleanup

### 1.1 Remove test_e2e.py
The file `/workspace/test_e2e.py` is an untracked manual test script. Review if it contains anything worth preserving, then delete it.

### 1.2 Decide on youtube_agent_planner package
The `/workspace/src/youtube_agent_planner/` directory contains the separated Planner/DAG pattern. Options:
- **Keep untracked** - Leave for future use without committing
- **Commit separately** - Add as a separate package with its own entry point
- **Delete** - If not needed

Related untracked files:
- `docs/PLANNER_DAG_PATTERN.md`
- `docs/V2_IMPLEMENTATION_LOG.md`
- `tests/test_planner_dag.py`

---

## Task 2: Add CLI Flags for max_transcripts

### Goal
Allow users to configure the maximum number of transcripts to fetch via CLI flag.

### Implementation Steps

1. **Update CLI argument parser** in `src/youtube_agent_v2/cli/main.py`:
   ```python
   parser.add_argument(
       "--max-transcripts",
       type=int,
       default=5,
       help="Maximum number of transcripts to fetch (default: 5)"
   )
   ```

2. **Pass to Synthesizer** - The Synthesizer should accept `max_transcripts` and include it in the initial state:
   ```python
   # In Synthesizer.process() or similar entry point
   initial_state = {
       "original_request": user_request,
       "max_transcripts": max_transcripts,
   }
   ```

3. **Verify it reaches TranscriptAgent** - The agent already reads from state:
   ```python
   # src/youtube_agent_v2/agents/transcript.py:194
   max_transcripts = state.get("max_transcripts", 5)
   ```

4. **Add test** - Verify the flag flows through the system correctly.

### Files to modify
- `src/youtube_agent_v2/cli/main.py` - Add CLI flag
- `src/youtube_agent_v2/agents/synthesizer.py` - Pass to initial state
- `tests/test_v2_autonomous.py` - Add test for configurable max_transcripts

---

## Task 3: Blog Post Series

### Overview
Two-part blog series. Full outline in `docs/BLOG_POST_PLAN.md`.

| Post | Focus | Status | Length |
|------|-------|--------|--------|
| **Part 1** | V1 Architecture | Outline complete, needs writing | ~3,000 words |
| **Part 2** | V2 Coordination Patterns | Outline needs updating for parallel execution | ~4,000 words |

---

### Part 1: V1 Architecture (~3,000 words)
**Title options**: "Architecting Multi-Agent Systems: Lessons from Building a YouTube Research Assistant"

**Key sections**:
1. Introduction - The AI agent landscape, production architecture challenge
2. The Architecture Challenge - Why agent code gets messy
3. **Tools vs Services** (core insight) - LLM interface vs business logic separation
4. Domain-Driven Organization - DDD-aligned services
5. Agent Design - Single responsibility, orchestrator pattern
6. Testing Strategy - Kent Beck's approach, mock boundaries
7. Lessons Learned

**Source files**:
- `src/youtube_agent/` - V1 implementation
- `docs/DESIGN_PHILOSOPHY.md` - Architectural rationale
- `tests/` - Testing patterns

---

### Part 2: V2 Coordination Patterns (~4,000 words)
**Title options**: "Beyond the Orchestrator: Multi-Agent Coordination Patterns"

**Current outline needs updates** for recent implementation work:

1. **Add Parallel Execution section** - The outline mentions patterns but doesn't cover:
   - `HandoffResult.fan_out()` for triggering parallel tasks
   - `TaskGroup` for tracking parallel completion
   - Video interleaving for diversity
   - The `is_parallel_task` flag pattern

2. **Update robustness features** - Add coverage for:
   - Result recovery from `state["parallel_results"]`
   - LLM-based video selection with channel preferences
   - LLM-based filename generation
   - Graceful degradation on partial failures

3. **Simplify pattern comparison** - The outline shows 4 patterns, but V2 unified into:
   - V1 Orchestrator (`youtube-agent`) - Conversational
   - V2 Autonomous + Queue (`youtube-agent-v2`) - Goal-driven batch (this is the focus)
   - Planner + DAG (`youtube-agent-planner`) - Explicit planning (separate package)

**Key sections to write/update**:
1. Introduction - Orchestrator limitations
2. Event-Driven Self-Selection - Queue with zero CPU idle
3. Autonomous Agent Chains - Goal reasoning, HandoffResult, intent routing
4. **NEW: Parallel Execution** - Fan-out/fan-in, TaskGroup coordination
5. **NEW: Robustness Features** - Recovery, interleaving, LLM selection
6. Choosing the Right Pattern - Decision flowchart
7. Implementation Tips
8. Conclusion

**Source files**:
- `docs/AUTONOMOUS_PATTERN.md` - Pattern overview with diagrams
- `docs/V2_IMPLEMENTATION_PLAN.md` - Technical details, robustness features
- `src/youtube_agent_v2/patterns/self_selection.py` - Pool coordination, fan-out
- `src/youtube_agent_v2/agents/` - Agent implementations with LLM reasoning
- `src/youtube_agent_v2/core/models/handoff.py` - HandoffResult with fan_out()

---

### Writing Approach

1. **Part 1 first** - More stable, V1 architecture is complete
2. **Part 2 after** - Incorporate recent parallel execution work

**Output files**:
- `docs/BLOG_POST_PART1.md` - Full Part 1 content
- `docs/BLOG_POST_PART2.md` - Full Part 2 content
- Update `docs/BLOG_POST_PLAN.md` - Mark sections as complete

---

## Running Tests

```bash
# All V2 tests
uv run pytest tests/test_v2_autonomous.py tests/test_v2_self_selection.py tests/test_v2_parallel.py -v

# Quick smoke test
uv run pytest tests/test_v2_autonomous.py -v --tb=short
```

---

## Key Files Reference

| Component | Path |
|-----------|------|
| CLI Entry | `src/youtube_agent_v2/cli/main.py` |
| Synthesizer | `src/youtube_agent_v2/agents/synthesizer.py` |
| TranscriptAgent | `src/youtube_agent_v2/agents/transcript.py` |
| Self-Selection Pool | `src/youtube_agent_v2/patterns/self_selection.py` |
| Blog Plan | `docs/BLOG_POST_PLAN.md` |
| Pattern Docs | `docs/AUTONOMOUS_PATTERN.md` |
