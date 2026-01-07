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

## V2: Multi-Agent Patterns

YouTube Agent V2 (`youtube-agent-v2`) explores alternative multi-agent coordination patterns beyond the V1 orchestrator.

### Available Patterns

```bash
# View all patterns
uv run youtube-agent-v2 patterns
```

| Pattern | Description | Best For |
|---------|-------------|----------|
| **dispatcher** | Central coordinator assigns tasks to capable agents | Simple single-task operations |
| **self-selection** | Agents compete to claim tasks from a queue | Scalable systems, load balancing |
| **planner** | LLM creates execution DAG, parallel execution with dependencies | Complex multi-step workflows |
| **autonomous** | Agents reason about goals and hand off to each other | Adaptive, emergent workflows |

### Quick Start

```bash
# List registered agents
uv run youtube-agent-v2 agents

# Simple commands (default: dispatcher pattern)
uv run youtube-agent-v2 search "python async tutorial"
uv run youtube-agent-v2 transcript VIDEO_ID
uv run youtube-agent-v2 summarize VIDEO_ID

# Use a different pattern
uv run youtube-agent-v2 -p planner search "kamado cooking tips"
uv run youtube-agent-v2 -p self-selection search "machine learning"
uv run youtube-agent-v2 -p autonomous chat -r "Find videos about cooking and summarize them"

# Interactive chat
uv run youtube-agent-v2 chat
uv run youtube-agent-v2 -p planner chat

# Single request (non-interactive)
uv run youtube-agent-v2 -p planner chat -r "Find videos about grilling and summarize them"
```

### Pattern Details

#### Dispatcher (default)
Central coordinator pulls tasks from a queue and assigns them to the first capable agent. Good for controlled execution with simple selection logic.

#### Self-Selection
Agents autonomously watch the queue and compete to claim tasks they can handle. Provides natural load balancing and scales well with many agents.

#### Planner (recommended for complex tasks)
An LLM-powered Planner creates an execution DAG (Directed Acyclic Graph) upfront, then the DAGExecutor runs steps with:
- **Parallel execution** of independent steps
- **Dependency tracking** between steps
- **Variable resolution** (`$step_id.field` syntax)
- **Re-planning on failure** with partial results

Example DAG for "Find videos about kamado cooking and summarize them":
```
search → transcript_1 → summarize_1 ─┐
       → transcript_2 → summarize_2 ─┴→ final_synthesis
```

#### Autonomous
Agents receive the original goal and accumulated state, then reason about what to do next. Each agent decides whether to complete the task or hand off to another agent based on what's still needed.

```bash
# Autonomous chain: search → transcript → summarize
uv run youtube-agent-v2 -p autonomous chat -r "Find pork loin videos and summarize cooking temps"
```

The chain adapts based on the goal:
- Goal mentions "transcript" → SearchAgent hands off to TranscriptAgent
- Goal mentions "summarize" → TranscriptAgent hands off to SummarizeAgent
- Goal mentions "save" or "file" → SummarizeAgent hands off to WriterAgent

**Key differences from Planner:**
- No upfront planning - agents decide dynamically
- State accumulates as agents hand off
- More flexible for evolving requirements

### V1 vs V2

| Aspect | V1 Orchestrator | V2 Patterns |
|--------|-----------------|-------------|
| **Control** | LLM decides every step | Patterns define coordination |
| **Best for** | Conversational, reasoning-heavy | Batch processing, parallel execution |
| **Command** | `youtube-agent` | `youtube-agent-v2` |

See [docs/V2_IMPLEMENTATION_PLAN.md](docs/V2_IMPLEMENTATION_PLAN.md) for detailed architecture documentation.

---

## Development

```bash
uv sync --all-extras
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires network)
uv run ruff check src tests      # Lint code
uv run mypy src                  # Type check
```
