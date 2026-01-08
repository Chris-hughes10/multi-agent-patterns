# V2 Implementation Notes

Notes from building `youtube_autonomous_agents` - useful for the blog post.

---

## Key Insight: V1 vs V2

| Aspect | V1 Orchestrator | V2 Autonomous |
|--------|-----------------|---------------|
| Control | Central LLM coordinates every step | Agents hand off directly to each other |
| Flow | User → Orchestrator → Agent → Orchestrator → Agent → User | User → Agent A → Agent B → Agent C → User |
| Who thinks? | Only the orchestrator reasons | Every agent reasons about the goal |

---

## What Worked

1. **Capability-based routing** - Agents declare what they can do, tasks declare what they need. Clean decoupling.

2. **Event-driven queue** - Zero CPU when idle, instant wake on new tasks. Much better than polling.

3. **Goal-aware reasoning** - Agents that see the full goal make better handoff decisions than keyword matching.

4. **Reusing V1 services** - V2 agents are thin wrappers around V1 tools. No duplication.

---

## What Didn't Work

1. **Built both Dispatcher and Self-Selection** - Realized they're nearly identical. Wasted effort. Should have picked one.

2. **Planner/DAG complexity** - Over-engineered. Variable resolution, re-planning, DAG validation added lots of code for marginal benefit in this use case.

3. **Keyword-based intent routing** - Too brittle. "Summarize the transcripts" matched "transcript" and routed wrong. LLM routing is more robust but slower.

4. **Multiple patterns in one CLI** - Confusing. Users shouldn't choose `--pattern autonomous` vs `--pattern planner`.

---

## Bugs Worth Mentioning

| Problem | Root Cause | Fix |
|---------|------------|-----|
| Wrong agent for "get X and summarize" | LLM router picked last step, not first | Changed prompt to ask for FIRST step |
| Agents looping on same task | No tracking of declined tasks | Track declined task IDs per agent |
| Single transcript failure killed everything | No error isolation | Per-item try/except with continuation |

---

## Recommendations

- Start with sequential handoffs - covers most cases
- Add LLM reasoning early - keyword matching fails on real queries
- One pattern per tool - don't make users choose coordination strategies
- Test with natural language queries - synthetic tests miss edge cases
