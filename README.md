# YouTube Agent

Multi-agent system for YouTube transcript search and summarization using Microsoft Agent Framework.

## Features

- **Multi-agent architecture**: Orchestrator coordinates specialized Search, Transcript, and Summarize agents
- **Conversation memory**: The agent remembers context from previous messages in the session
- **Smart caching**: Transcripts are automatically cached to avoid re-fetching
- **Context-aware**: The agent automatically knows what transcripts are stored and uses them before searching YouTube

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

## Architecture

The system uses a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                         cli/                            │
│                 Command-line interface                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                       agents/                           │
│              Orchestrator + Specialized Agents          │
│         (Search, Transcript, Summarize, Writer)         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                       tools/                            │
│           LLM-callable functions (thin wrappers)        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      services/                          │
│                Business logic classes                   │
│          (YouTube API, Storage, Summarizer)             │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                       models/                           │
│                 Data structures & config                │
└─────────────────────────────────────────────────────────┘
```

### Multi-Agent System

The orchestrator coordinates four specialized agents:

| Agent | Responsibility | Calls |
|-------|---------------|-------|
| **SearchAgent** | Find videos on YouTube | YouTube search |
| **TranscriptAgent** | Fetch and cache transcripts | YouTube transcript API |
| **SummarizeAgent** | Generate summaries | Azure OpenAI |
| **WriterAgent** | Export to markdown files | File system |

### Key Design Patterns

- **Tools vs Services**: Tools are thin LLM-callable wrappers. Services contain the real business logic.
- **Domain-Driven**: Services organized by domain (`youtube.py`, `storage.py`, `summarizer.py`)
- **Context Injection**: `TranscriptContextProvider` tells the orchestrator what's cached before each call

See [DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md) for detailed architectural decisions.

## V2: Goal-Aware Multi-Agent System

YouTube Agent V2 (`youtube-goal-aware`) uses **goal-aware agents with dispatcher-based routing** - an LLM router assigns tasks, but agents can validate and reject assignments with reasoning.

### How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    User Request                         │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│                    Synthesizer                          │
│         (analyzes request, detects parallelism)         │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│              LLM Intent Router (Dispatcher)             │
│         (routes task to best agent for intent)          │
└────────────────────────┬────────────────────────────────┘
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
  ┌─────────┐      ┌───────────┐     ┌─────────┐
  │ Search  │      │Transcript │     │Summarize│ ...
  └────┬────┘      └─────┬─────┘     └────┬────┘
       └─────────────────┴────────────────┘
                         ↓
              validate → accept/reject → execute
                         ↓
              ┌──────────┴──────────┐
              │                     │
           complete            handoff
              ↓                     ↓
           DONE              Post new task
                             (re-route if rejected)
```

**Key features:**
- **Dispatcher + confirmation**: LLM routes tasks, agents validate before executing
- **Agent rejection with re-routing**: Mis-routed tasks get re-assigned with context
- **Goal-aware handoffs**: Agents reason about user's goal, hand off to continue chain
- **State accumulation**: Context builds up as the chain progresses

### Quick Start

```bash
# List registered agents
uv run youtube-goal-aware agents

# Simple commands
uv run youtube-goal-aware search "python async tutorial"
uv run youtube-goal-aware transcript VIDEO_ID

# Interactive chat
uv run youtube-goal-aware chat

# Single request - agents chain automatically
uv run youtube-goal-aware chat -r "Find videos about cooking and summarize them"

# Limit transcripts fetched (default: 5)
uv run youtube-goal-aware chat -t 3 -r "Find BBQ videos and summarize them"
```

### Example Flow

```bash
uv run youtube-goal-aware chat -r "Find pork loin videos and summarize cooking temps"
```

The agents chain automatically based on the goal:
1. **SearchAgent** finds videos → hands off to TranscriptAgent
2. **TranscriptAgent** fetches transcripts → hands off to SummarizeAgent
3. **SummarizeAgent** generates summary → completes (or hands off to WriterAgent if "save" is mentioned)

### DAG Planner (Separate Package)

For complex multi-step workflows with explicit planning and parallel execution, use the separate `youtube-agent-planner`:

```bash
uv run youtube-agent-planner chat -r "Find videos about grilling and summarize them"
```

The planner creates an execution DAG upfront with dependency tracking and parallel execution. See [docs/blog/part3_planner.md](docs/blog/part3_planner.md) for details.

### V1 vs V2

| Aspect | V1 Orchestrator | V2 Goal-Aware |
|--------|-----------------|---------------|
| **Control** | LLM decides every step | Dispatcher routes, agents validate |
| **Best for** | Conversational, reasoning-heavy | Goal-driven batch processing |
| **Command** | `youtube-agent` | `youtube-goal-aware` |

See [docs/blog/part2_goal_aware.md](docs/blog/part2_goal_aware.md) for detailed architecture documentation.

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
