# Architecting Multi-Agent Systems

A reference implementation exploring three multi-agent coordination patterns, built with the [Microsoft Agent Framework](https://github.com/microsoft/agents).

**This repo accompanies a 3-part blog series:**

1. **[Part 1: Clean Architecture](docs/blog/part1_architecture.md)** — Tools vs services, DDD for agents, the orchestrator pattern
2. **[Part 2: Goal-Aware Agents](docs/blog/part2_goal_aware.md)** — Distributed coordination, dispatcher pattern, event-driven handoffs
3. **[Part 3: Planner + DAG](docs/blog/part3_planner.md)** — Upfront planning, predictable costs, parallel execution

## The Problem Domain

YouTube cooking channels contain expert knowledge locked in video format. This project automates: search → transcript → summarize → save. A non-trivial but focused task—complex enough to require multiple agents, simple enough to highlight architectural decisions.

## Three Patterns Explored

| Pattern | Package | Key Idea | Best For |
|---------|---------|----------|----------|
| **V1 Orchestrator** | `youtube_agent_orchestrator` | Central LLM coordinates specialists | Conversational interfaces |
| **V2 Goal-Aware** | `youtube_goal_agents` | Agents reason about goals, hand off to each other | Adaptive workflows |
| **V3 Planner+DAG** | `youtube_agent_planner` | Single planning call, mechanical execution | Batch processing, cost control |

### Quick Comparison

```
V1 Orchestrator:  User → Orchestrator → Agent A → Orchestrator → Agent B → User
V2 Goal-Aware:    User → Agent A → Agent B → Agent C → User
V3 Planner+DAG:   User → Planner → [parallel execution] → User
```

| Metric | V1 Orchestrator | V2 Goal-Aware | V3 Planner+DAG |
|--------|-----------------|---------------|----------------|
| LLM Calls | 17-34 (high variance) | ~21 (low variance) | ~3 (zero variance) |
| Adaptability | High | High | Low |
| Predictability | Low | High | Very High |

## Key Architectural Insights

The blog series explores principles that apply regardless of framework:

- **Tools vs Services** — Tools are thin LLM adapters; services contain business logic. This separation unlocks testability and reuse.
- **Domain-Driven Design** — Bounded contexts map naturally to agent systems. Group by external system (YouTube, Storage), not by function.
- **Single Responsibility Agents** — Each agent does one thing. Debugging becomes straightforward: bad summary? Check SummarizeAgent.
- **Goal-Aware Reasoning** — When agents understand *why* they're asked to do something, they make better decisions about *what* happens next.

## Features

- **Three coordination patterns** implemented and benchmarked
- **Layered architecture** with clear separation of concerns
- **Parallel execution** via DAG dependency tracking (V3) or fan-out/fan-in (V2)
- **Conversation memory** for interactive sessions (V1)
- **Smart caching** to avoid re-fetching transcripts

## Setup

```bash
uv sync
```

## Configuration

Create a `.env` file with your Azure OpenAI credentials:

```bash
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_API_VERSION=2025-04-01-preview
AZURE_TENANT_ID=your-tenant-id

# Optional: YouTube Data API key for higher rate limits
# YOUTUBE_API_KEY=your-youtube-api-key
```

### Proxy Configuration (Important for Cloud/CI environments)

YouTube blocks requests from most data center IP addresses (AWS, Azure, GCP, GitHub Codespaces, etc.). If you're running this agent in a cloud environment, you'll need a **residential proxy** to fetch transcripts.

```bash
# Add to your .env file
PROXY_URL=http://user:pass@your-residential-proxy:port
```

> **Note**: Standard data center proxies won't work - YouTube specifically blocks these. You'll need a residential proxy service (e.g., Bright Data, Oxylabs, SmartProxy) that routes through real residential IPs.

If you see errors like `TranscriptsDisabled` or connection timeouts when fetching transcripts, this is likely the cause.

### LLM Sampling Settings

Control response determinism with optional temperature and seed settings:

```bash
# Add to your .env file
LLM_TEMPERATURE=0.7  # 0.0=deterministic, 1.0=creative (default: 0.7)
LLM_SEED=42          # Fixed seed for reproducible outputs (default: 42)
```

- **Temperature**: Lower values (0.0-0.3) produce more focused, deterministic responses. Higher values (0.7-1.0) produce more creative, varied responses.
- **Seed**: When set, helps produce more consistent outputs across runs (model-dependent).

## Usage

### Interactive Chat (Default)

Start an interactive session with the AI agent:

```bash
uv run youtube-agent
```

Or with a single request:

```bash
uv run youtube-agent chat "Find videos about Python async programming and summarize the top result"
```

By default, transcripts are automatically saved. To disable:

```bash
uv run youtube-agent chat --no-store "summarize this video"
```

### Search Videos

Search YouTube for videos:

```bash
uv run youtube-agent search "machine learning tutorial"
uv run youtube-agent search "python asyncio" -n 10  # Get 10 results
```

### Fetch Transcript

Get the full transcript of a video:

```bash
uv run youtube-agent transcript "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
uv run youtube-agent transcript dQw4w9WgXcQ  # Video ID also works
uv run youtube-agent transcript VIDEO_ID --save  # Save to data/transcripts/
```

### Summarize Video

Fetch transcript and generate an AI summary:

```bash
uv run youtube-agent summarize "https://www.youtube.com/watch?v=VIDEO_ID"
uv run youtube-agent summarize VIDEO_ID --no-save  # Don't save to storage
```

### List Stored Transcripts

View all saved transcripts and summaries:

```bash
uv run youtube-agent list
```

### Lookup Stored Transcript

Retrieve a previously saved transcript:

```bash
uv run youtube-agent lookup VIDEO_ID
```

### Debug Mode

Human-friendly status updates (e.g., `[15:55:22] .. Thinking...`) are always shown by default.

For full debug logging:

```bash
uv run youtube-agent --debug chat "summarize a video about Python"
```

Debug mode writes detailed logs to `data/logs/session_TIMESTAMP.log` for troubleshooting.

## Troubleshooting

### "Transcripts are disabled" or Connection Errors

If you see errors like `TranscriptsDisabled` or connection timeouts when fetching transcripts:

**Cause**: YouTube blocks requests from data center IP addresses (AWS, Azure, GCP, GitHub Codespaces, etc.)

**Solution**:
1. Set up a residential proxy service (e.g., Bright Data, Oxylabs, SmartProxy)
2. Add to your `.env`:
   ```bash
   PROXY_URL=http://user:pass@your-residential-proxy:port
   ```

**Note**: Standard data center proxies won't work - you need residential IPs.

### Azure OpenAI Authentication Issues

If you see authentication errors:

**Using Azure AD** (recommended):
1. Run `az login` to authenticate
2. Ensure `AZURE_TENANT_ID` is set in `.env`

**Using API Key**:
```bash
AZURE_OPENAI_API_KEY=your-key-here
```

### Tests Failing

- **Unit tests**: Should work without any credentials (external APIs are mocked)
- **Integration tests**: Require valid Azure OpenAI credentials and network access
- Run unit tests only: `uv run pytest` (integration tests are skipped by default)

## Running the Examples

Each pattern has its own CLI entry point. Try the same request across all three to see how they differ:

### V1 Orchestrator — Conversational coordination

```bash
uv run youtube-agent chat
# Or single request:
uv run youtube-agent chat "Find videos about pork loin and summarize cooking temps"
```

The orchestrator decides what to do at each step, maintaining conversation context.

### V2 Goal-Aware — Distributed agent coordination

```bash
uv run youtube-goal-aware chat
# Or single request:
uv run youtube-goal-aware chat -r "Find videos about pork loin and summarize cooking temps"
```

Agents reason about the goal and hand off to each other. Use `-v` for verbose output showing agent decisions.

### V3 Planner+DAG — Upfront planning

```bash
uv run youtube-agent-planner chat
# Or single request:
uv run youtube-agent-planner chat -r "Find videos about pork loin and summarize cooking temps"
```

Creates an explicit execution plan before running. You can see the full DAG before execution starts.

### Utility Commands

All patterns share these utilities:

```bash
uv run youtube-agent search "python async tutorial"    # Search YouTube
uv run youtube-agent transcript VIDEO_ID               # Fetch transcript
uv run youtube-agent list                              # Show cached transcripts
```

---

## Development

```bash
uv sync --all-extras
uv run pytest                    # Run unit tests (mocked external services)
uv run pytest -m integration     # Run integration tests (requires Azure OpenAI + network)
uv run ruff check src tests      # Lint code
uv run mypy src                  # Type check
```

### Integration Tests

Integration tests require real Azure OpenAI credentials and network access. They're marked with `@pytest.mark.integration` and skipped by default.

**To run integration tests:**

1. Set up your `.env` file with valid Azure OpenAI credentials
2. Ensure you have network access to YouTube and Azure OpenAI
3. Run: `uv run pytest -m integration`

**Note**: Integration tests may incur Azure OpenAI API costs and take longer to complete.
