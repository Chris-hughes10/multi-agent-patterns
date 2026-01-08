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

## Architecture

The system uses a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                        cli/                             │
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

## V2: Autonomous Multi-Agent System

YouTube Agent V2 (`youtube-agent-v2`) uses **autonomous agents with event-driven self-selection** - a unified coordination pattern where agents reason about goals and hand off work via a shared queue.

### How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    User Request                         │
└────────────────────────┬────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│              Event-Driven Task Queue                    │
└────────────────────────┬────────────────────────────────┘
                         │ (agents notified instantly)
         ┌───────────────┼───────────────┐
         ↓               ↓               ↓
    ┌─────────┐     ┌─────────┐     ┌─────────┐
    │ Search  │     │Transcr. │     │ Writer  │
    └────┬────┘     └────┬────┘     └────┬────┘
         └───────────────┴───────────────┘
                         ↓
              can_handle? → claim → execute
                         ↓
              ┌──────────┴──────────┐
              │                     │
           complete            handoff
              ↓                     ↓
           DONE              Post new task
                             (loop continues)
```

**Key features:**
- **Event-driven queue**: Zero CPU usage when idle (no polling)
- **Self-selection**: Agents compete to claim tasks they can handle
- **Autonomous handoffs**: Agents reason about the goal and hand off to the next agent
- **State accumulation**: Context builds up as the chain progresses

### Quick Start

```bash
# List registered agents
uv run youtube-agent-v2 agents

# Simple commands
uv run youtube-agent-v2 search "python async tutorial"
uv run youtube-agent-v2 transcript VIDEO_ID

# Interactive chat
uv run youtube-agent-v2 chat

# Single request - agents chain automatically
uv run youtube-agent-v2 chat -r "Find videos about cooking and summarize them"

# Limit transcripts fetched (default: 5)
uv run youtube-agent-v2 chat -t 3 -r "Find BBQ videos and summarize them"
```

### Example Flow

```bash
uv run youtube-agent-v2 chat -r "Find pork loin videos and summarize cooking temps"
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

The planner creates an execution DAG upfront with dependency tracking and parallel execution. See [docs/PLANNER_DAG_PATTERN.md](docs/PLANNER_DAG_PATTERN.md) for details.

### V1 vs V2

| Aspect | V1 Orchestrator | V2 Autonomous |
|--------|-----------------|---------------|
| **Control** | LLM decides every step | Agents self-coordinate via queue |
| **Best for** | Conversational, reasoning-heavy | Goal-driven batch processing |
| **Command** | `youtube-agent` | `youtube-agent-v2` |

See [docs/AUTONOMOUS_PATTERN.md](docs/AUTONOMOUS_PATTERN.md) for detailed architecture documentation.

---

## Development

```bash
uv sync --all-extras
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires network)
uv run ruff check src tests      # Lint code
uv run mypy src                  # Type check
```
