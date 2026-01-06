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

The system uses a multi-agent architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                         │
│  - Coordinates all agents                               │
│  - Maintains conversation memory (AgentThread)          │
│  - Receives context about stored transcripts            │
└─────────────────────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   ┌─────────┐ ┌──────────┐ ┌───────────┐
   │ Search  │ │Transcript│ │ Summarize │
   │  Agent  │ │  Agent   │ │   Agent   │
   └─────────┘ └──────────┘ └───────────┘
        │           │              │
        ▼           ▼              ▼
   YouTube API   YouTube     Azure OpenAI
                Transcripts
```

- **SearchAgent**: Searches YouTube for videos
- **TranscriptAgent**: Fetches and caches video transcripts (the only agent that fetches from YouTube)
- **SummarizeAgent**: Summarizes text content (does not fetch)

### Context Provider

The `TranscriptContextProvider` automatically injects information about stored transcripts before each agent call. This allows the orchestrator to make smart decisions about when to use cached data vs. searching YouTube.

## Development

```bash
uv sync --all-extras
uv run pytest                    # Run unit tests
uv run pytest -m integration     # Run integration tests (requires network)
uv run ruff check src tests      # Lint code
uv run mypy src                  # Type check
```
