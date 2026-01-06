# Multi-Agent YouTube Transcript System - Implementation Plan

## Overview

Build a multi-agent system using Microsoft Agent Framework with four agents:
1. **Search Agent** - Find YouTube videos by topic
2. **Transcript Agent** - Fetch, store, and retrieve raw transcripts
3. **Summarize Agent** - Generate summaries from transcripts
4. **Orchestrator Agent** - Coordinate the workflow

## Architecture

```
User Query: "What are the best practices for RAG?"
                         │
                         ▼
    ┌─────────────────────────────────────────────────────────┐
    │                   ORCHESTRATOR AGENT                     │
    │              (Coordinates all sub-agents)                │
    └─────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌─────────────┐ ┌───────────────┐ ┌────────────────┐
   │SEARCH AGENT │ │TRANSCRIPT     │ │SUMMARIZE AGENT │
   │             │ │AGENT          │ │                │
   │• search     │ │• fetch        │ │• summarize     │
   │  youtube    │ │• store        │ │  transcript    │
   │             │ │• lookup       │ │• synthesize    │
   │             │ │• list stored  │ │  multiple      │
   └─────────────┘ └───────────────┘ └────────────────┘
```

## Orchestration Pattern

Use **Agents-as-Tools** pattern:
- Orchestrator maintains central control
- Sub-agents are called like tools
- Orchestrator dynamically decides synthesis format based on user intent

## Agent Responsibilities

| Agent | Tools | Purpose |
|-------|-------|---------|
| **Search** | `search_youtube` | Find videos by topic/query |
| **Transcript** | `fetch_transcript`, `store_transcript`, `lookup_transcript`, `list_transcripts` | Manage raw transcripts |
| **Summarize** | `summarize_transcript`, `summarize_text` | Generate summaries |
| **Orchestrator** | Sub-agents as tools | Coordinate and synthesize |

## Implementation Steps

### Step 1: Add Dependencies
- `youtube-search-python` - For searching YouTube without API key
- Verify `agent-framework` is installed

### Step 2: Create YouTube Search Tool
**File:** `src/youtube_agent/tools/search.py`

```python
from typing import Annotated
from pydantic import Field

def search_youtube(
    query: Annotated[str, Field(description="Search query for YouTube videos")],
    max_results: Annotated[int, Field(description="Maximum number of results")] = 5
) -> list[dict]:
    """Search YouTube for videos matching the query.

    Returns list of video info with id, title, channel, duration.
    """
```

### Step 3: Create Search Agent
**File:** `src/youtube_agent/agents/search_agent.py`

```python
search_agent = chat_client.create_agent(
    name="SearchAgent",
    instructions="""You search YouTube for videos about given topics.
    Return a list of relevant video IDs with titles.""",
    tools=[search_youtube]
)
```

### Step 4: Create Transcript Agent
**File:** `src/youtube_agent/agents/transcript_agent.py`

```python
transcript_agent = chat_client.create_agent(
    name="TranscriptAgent",
    instructions="""You manage YouTube video transcripts.
    You can fetch new transcripts, store them, look up existing ones, and list what's stored.""",
    tools=[fetch_transcript, store_transcript, lookup_transcript, list_transcripts]
)
```

### Step 5: Create Summarize Agent
**File:** `src/youtube_agent/agents/summarize_agent.py`

```python
summarize_agent = chat_client.create_agent(
    name="SummarizeAgent",
    instructions="""You summarize video transcripts.
    You can summarize individual transcripts or synthesize insights from multiple transcripts.""",
    tools=[summarize_transcript, summarize_text]
)
```

### Step 6: Create Orchestrator Agent
**File:** `src/youtube_agent/agents/orchestrator.py`

```python
orchestrator = chat_client.create_agent(
    name="Orchestrator",
    instructions="""You coordinate YouTube research tasks by delegating to specialized agents:

    - SearchAgent: Find videos on YouTube
    - TranscriptAgent: Fetch/store/retrieve transcripts
    - SummarizeAgent: Summarize transcripts

    Based on the user's request, decide:
    1. Which agents to use and in what order
    2. Whether to provide detailed output or synthesized summary
    3. How to format the final response

    For research queries, typically: Search → Fetch transcripts → Summarize → Synthesize answer""",
    tools=[search_agent, transcript_agent, summarize_agent]
)
```

### Step 7: Create Main Entry Point
**File:** `src/youtube_agent/agents/main.py`

- Create chat client with Azure credentials
- Wire up all agents
- Provide CLI interface using `func-to-script`

### Step 8: Add Tests
- Unit tests with mocked agents
- Integration tests for full workflow

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add `youtube-search-python` dependency |
| `src/youtube_agent/tools/search.py` | Create | YouTube search functionality |
| `src/youtube_agent/agents/search_agent.py` | Create | Search Agent definition |
| `src/youtube_agent/agents/transcript_agent.py` | Create | Transcript Agent definition |
| `src/youtube_agent/agents/summarize_agent.py` | Create | Summarize Agent definition |
| `src/youtube_agent/agents/orchestrator.py` | Create | Orchestrator Agent definition |
| `src/youtube_agent/agents/main.py` | Create | Main entry point and CLI |
| `src/youtube_agent/agents/__init__.py` | Modify | Export agents |
| `tests/test_search.py` | Create | Search tool tests |
| `tests/test_agents.py` | Create | Agent integration tests |

## Key Design Decisions

1. **Agents-as-Tools Pattern** - Orchestrator uses sub-agents as tools, maintaining central control
2. **4-Agent Architecture** - Separate Transcript and Summarize for flexibility
3. **Dynamic Synthesis** - Orchestrator decides output format based on user intent
4. **Async-First** - All agent operations are async (asyncio)
5. **Azure CLI Auth** - Reuse existing `AzureCliCredential` pattern with tenant_id support
6. **Tool Reuse** - Existing tools wrapped for agent compatibility
7. **func-to-script CLI** - Simple CLI using decorated functions

## Example Workflows

### "Get transcript for video X"
```
User → Orchestrator → TranscriptAgent.fetch_transcript(X) → Return raw transcript
```

### "Summarize video X"
```
User → Orchestrator → TranscriptAgent.fetch_transcript(X) → SummarizeAgent.summarize() → Return summary
```

### "Research RAG best practices"
```
User → Orchestrator → SearchAgent.search("RAG best practices")
                    → TranscriptAgent.fetch_transcript(video1, video2, video3) [parallel]
                    → SummarizeAgent.summarize(each transcript)
                    → Orchestrator synthesizes final answer
```

## Testing Strategy

1. **Unit Tests** - Mock the Agent Framework, test tool logic
2. **Integration Tests** - Mark with `@pytest.mark.integration`, test real agent execution
3. **Manual Testing** - CLI interface for interactive testing

## Known Limitations & Future Work

### YouTube Transcript API IP Blocking

YouTube blocks transcript requests from cloud provider IPs (AWS, Azure, GCP, etc.). The `youtube-transcript-api` library works fine from residential IPs but fails in cloud/devcontainer environments.

**Current Status:** Search works (HTML scraping), but transcript fetching is blocked in cloud environments.

**Solution:** Added proxy support to route transcript requests through a VPN/proxy service.

### Proxy Support (Implemented)

1. **Add proxy configuration to Settings**
   ```python
   # In models/config.py
   proxy_url: str | None = Field(default=None, description="SOCKS5 or HTTP proxy URL")
   ```

2. **Update TranscriptFetcher to use proxy**
   ```python
   # youtube-transcript-api supports proxies
   YouTubeTranscriptApi.get_transcript(
       video_id,
       proxies={"https": settings.proxy_url}
   )
   ```

3. **Proxy Options**
   - SOCKS5 proxy via Surfshark VPN (or other VPN with SOCKS5 support)
   - HTTP/HTTPS proxy service
   - Self-hosted proxy on residential IP

4. **Environment Configuration**
   ```bash
   # .env
   PROXY_URL=socks5://user:pass@proxy.surfshark.com:1080
   ```

### Other Future Enhancements

- Vector storage for semantic search over stored transcripts
- Batch processing for multiple videos
- Rate limiting and retry logic
- YouTube Data API integration as fallback
