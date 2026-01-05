# Agent Frameworks Research & Learning Plan

## Executive Summary

This document provides research on AI agent frameworks with a focus on Microsoft's new Agent Framework, industry adoption trends, and a practical project plan for building a YouTube transcript search/summarization system.

---

## 1. Microsoft Agent Framework (The Big News)

### What Happened?

Microsoft has unified **AutoGen** and **Semantic Kernel** into a single framework called **Microsoft Agent Framework**. This is now in public preview.

**Key Points:**
- **Not a replacement** - It's a unification that builds on both frameworks
- **Same teams** - Built by the Semantic Kernel and AutoGen teams
- **Think of it as Semantic Kernel v2.0** with AutoGen's multi-agent capabilities
- **Supports Python and .NET**
- **Native MCP (Model Context Protocol) integration**

### Why This Matters for You

As a Microsoft employee, this is the strategic direction for agentic AI. Learning this framework positions you well internally and gives you content for a blog post that would be very timely.

### Migration Path
- Semantic Kernel users: Framework is designed as the natural evolution
- AutoGen users: Migration guides available
- Microsoft will support Semantic Kernel for at least 1 year after Agent Framework goes GA

### Getting Started

```bash
# Install the framework (currently in preview)
pip install agent-framework --pre

# Or just Azure AI components
pip install agent-framework-azure-ai --pre
```

**Prerequisites:**
- Python 3.10+
- Azure OpenAI service endpoint
- Azure CLI authenticated
- Cognitive Services OpenAI User/Contributor role

### Resources
- [GitHub Repository](https://github.com/microsoft/agent-framework)
- [Official Samples](https://github.com/microsoft/Agent-Framework-Samples)
- [Microsoft Learn Quick Start](https://learn.microsoft.com/en-us/agent-framework/tutorials/quick-start)
- [PyPI Package](https://pypi.org/project/agent-framework/)
- [Introduction Overview](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)

---

## 2. Industry Landscape (2025)

### Market Statistics
- **70%+** of organizations leveraging AI in some form
- **Gartner predicts**: 33% of enterprise apps will have agentic AI by 2028 (up from <1% in 2024)
- **90%** of non-tech companies have or are planning agents in production

### Top Frameworks Comparison

| Framework | Market Position | Best For | Key Stats |
|-----------|-----------------|----------|-----------|
| **LangChain/LangGraph** | ~30% market share, 80K+ GitHub stars | Custom chat interfaces, tool integration | Used by LinkedIn, Uber, 400+ companies |
| **CrewAI** | Enterprise leader | Role-based multi-agent, content/research | 60% of Fortune 500, $18M Series A, 100K+ executions/day |
| **Microsoft Agent Framework** | New unified platform | Enterprise .NET/Python, Azure integration | Direct successor to SK + AutoGen |
| **OpenAI Agents SDK** | Growing | OpenAI-native workflows | Tight GPT integration |

### Industry Recommendations

> "Start with single-agent frameworks for MVPs. Scale to multi-agent frameworks once workflows mature."

### For Your Blog Post
This landscape comparison would be valuable content - many developers are confused about which framework to choose.

---

## 3. Technology Stack (Start Simple!)

### Local-First Approach (Recommended for Learning)

Start lightweight, scale to Azure later when needed.

| Component | Local Tool | Why |
|-----------|------------|-----|
| Vector Store | **ChromaDB** | `pip install chromadb` - zero config, runs embedded |
| Embeddings | OpenAI API or Azure OpenAI | text-embedding-3-small |
| LLM | OpenAI API or Azure OpenAI | GPT-4o-mini (cheap) or GPT-4o |
| Orchestration | Microsoft Agent Framework | The framework you're learning |
| Storage | Local filesystem | Keep it simple |

### Local Vector Database Options

| Database | Install | Best For | Limitation |
|----------|---------|----------|------------|
| **ChromaDB** | `pip install chromadb` | Prototyping, fastest setup, NumPy-like API | Not for 50M+ vectors |
| **LanceDB** | `pip install lancedb` | Multi-modal data, low memory | Slightly lower recall |
| **Qdrant** | Docker or `pip install qdrant-client` | Production-ready, filtered search | More setup |

**Recommendation**: ChromaDB. Integrates with LangChain, LlamaIndex, and most AI toolchains. Recently got 4x faster with Rust rewrite.

### Architecture Pattern (Local-First)

```
YouTube Videos
      ↓
[youtube-transcript-api] (Python library, no API key needed)
      ↓
Chunking + Embedding (OpenAI API)
      ↓
ChromaDB (Local vector store - zero config!)
      ↓
Microsoft Agent Framework (Agent with Tools)
      ↓
User Query → Search → Summarize → Response
```

### Later: Scale to Azure

When you're ready for production:

| Component | Upgrade To | Why |
|-----------|------------|-----|
| Vector Store | Azure AI Search | Hybrid search, new Agentic Retrieval (40% better!) |
| LLM/Embeddings | Azure OpenAI | Enterprise SLAs, private endpoints |
| Storage | Azure Blob Storage | Scalability |
| Hosting | Azure Container Apps | Production deployment |

---

## 4. YouTube Transcript Extraction

### Primary Tool: `youtube-transcript-api`

A Python library that extracts transcripts without requiring:
- API keys
- Headless browsers
- YouTube Data API quota

```bash
pip install youtube-transcript-api
```

```python
from youtube_transcript_api import YouTubeTranscriptApi

ytt_api = YouTubeTranscriptApi()
transcript = ytt_api.fetch("dQw4w9WgXcQ")  # video_id from URL

# Output includes timestamps
for entry in transcript:
    print(f"{entry['start']}: {entry['text']}")
```

### Features
- Auto-generated subtitle support
- Translation support
- Multiple output formats: JSON, SRT, VTT, CSV, TXT

### Limitations
- Age-restricted videos may not work
- Some videos disable transcripts
- Cookie auth currently broken

### Resources
- [PyPI](https://pypi.org/project/youtube-transcript-api/)
- [GitHub](https://github.com/jdepoix/youtube-transcript-api)

---

## 5. Project: YouTube Transcript Search & Summarization

### Project Goals
1. Extract transcripts from YouTube videos
2. Index them in a searchable vector database
3. Enable natural language search across all transcripts
4. Provide AI-powered summarization
5. (Optional) Build a simple chat interface

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│                    (CLI / Streamlit / API)                      │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Microsoft Agent Framework                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Search Tool │  │ Summarize   │  │ Transcript Fetch Tool   │  │
│  │             │  │ Tool        │  │ (youtube-transcript-api)│  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
         ┌──────────────────┐      ┌──────────────────┐
         │    ChromaDB      │      │   OpenAI API     │
         │  (Local Vectors) │      │ (Embeddings+LLM) │
         └──────────────────┘      └──────────────────┘
```

### Implementation Phases

#### Phase 1: Foundation (Simplest possible)
- [ ] Create Python project structure
- [ ] Implement transcript extraction with youtube-transcript-api
- [ ] Store transcripts as JSON files (key-value by video ID)
- [ ] Basic summarization by passing whole transcript to LLM

#### Phase 2: Agent Integration
- [ ] Set up Microsoft Agent Framework
- [ ] Create tools: fetch_transcript, summarize, lookup
- [ ] Build agent with tool orchestration
- [ ] Store summaries alongside transcripts

#### Phase 3: Optional - Vector Search (if needed)
- [ ] Add ChromaDB for semantic search across videos
- [ ] Implement chunking for very long transcripts
- [ ] Enable "search across all my videos" queries

#### Phase 4: Polish & Blog
- [ ] Add error handling and edge cases
- [ ] Create simple UI (Streamlit recommended)
- [ ] Write blog post documenting the journey
- [ ] Create GitHub repo with examples

### Do You Even Need Vector Embeddings?

**Great question to consider!** Modern LLMs have huge context windows:
- GPT-4o: 128K tokens (~100K words)
- GPT-4o-mini: 128K tokens (cheaper!)
- Claude: 200K tokens
- Gemini: 1M+ tokens

A typical 1-hour YouTube video transcript is ~10,000-15,000 words. **Most transcripts fit entirely in one context window.**

#### Simple Approach (Start Here!)

```
Video ID → JSON file with transcript → Pass whole thing to LLM → Done
```

| Storage | When to Use |
|---------|-------------|
| **JSON files** | < 50 videos, transcripts fit in context |
| **SQLite** | Need to query metadata, still fits in context |
| **ChromaDB** | 100+ videos, need semantic search across all |

#### When You DO Need Vector Search

- Searching across hundreds of videos: "Which video talked about X?"
- Very long transcripts (4+ hour videos) that exceed context
- Finding specific moments across a video library

### Minimal Viable Demo (Simplest Path)

```python
# This is literally all you need to start:
from youtube_transcript_api import YouTubeTranscriptApi
import json
from openai import OpenAI

# 1. Fetch transcript
transcript = YouTubeTranscriptApi().fetch("VIDEO_ID")
full_text = " ".join([t['text'] for t in transcript])

# 2. Store it
with open(f"transcripts/{video_id}.json", "w") as f:
    json.dump({"video_id": video_id, "text": full_text}, f)

# 3. Summarize (whole transcript fits in context!)
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Summarize this video transcript."},
        {"role": "user", "content": full_text}
    ]
)
```

---

## 6. Multi-Agent Architecture (The Fun Part!)

### Why Multi-Agent?

Instead of one monolithic agent, split responsibilities:

| Agent | Responsibility | Tools |
|-------|----------------|-------|
| **Search Agent** | Find relevant YouTube videos | youtube-search-python |
| **Transcript Agent** | Fetch & summarize transcripts | youtube-transcript-api, LLM |
| **Orchestrator** | Coordinate agents, aggregate results | Agent Framework workflows |

### YouTube Search Options

| Library | API Key? | Best For |
|---------|----------|----------|
| **youtube-search-python** | No | Full-featured, recommended |
| **youtube-search** | No | Simple scraping |
| **YouTube Data API v3** | Yes | Official, higher limits |

```bash
pip install youtube-search-python  # No API key needed!
```

```python
from youtubesearchpython import VideosSearch

search = VideosSearch('Microsoft Agent Framework tutorial', limit=5)
for video in search.result()['result']:
    print(f"{video['title']} - {video['id']}")
```

### Multi-Agent Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Query                                │
│            "What are the best practices for RAG?"               │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR AGENT                           │
│         (Coordinates workflow, aggregates results)              │
└─────────────────────────────────────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  │                  │
┌──────────────────────┐         │                  │
│    SEARCH AGENT      │         │                  │
│  youtube-search-python│        │                  │
│  → Find 5 videos     │         │                  │
└──────────────────────┘         │                  │
              │                  │                  │
              ▼                  │                  │
        [video_ids]              │                  │
              │                  │                  │
              ├──────────────────┼──────────────────┤
              ▼                  ▼                  ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ TRANSCRIPT AGENT │  │ TRANSCRIPT AGENT │  │ TRANSCRIPT AGENT │
│   (Video 1)      │  │   (Video 2)      │  │   (Video 3)      │
│  Fetch + Summary │  │  Fetch + Summary │  │  Fetch + Summary │
└──────────────────┘  └──────────────────┘  └──────────────────┘
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR AGENT                           │
│         Aggregates summaries → Final synthesized answer         │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Final Response                              │
│   "Based on 5 videos, the best practices for RAG are..."       │
└─────────────────────────────────────────────────────────────────┘
```

### Microsoft Agent Framework Orchestration Patterns

The framework provides built-in patterns for multi-agent coordination:

| Pattern | Description | Use Case |
|---------|-------------|----------|
| **Sequential** | Agents run one after another | Writer → Reviewer |
| **Concurrent** | Agents run in parallel | Multiple transcript fetches |
| **Hand-off** | One agent delegates to another | Search → Transcript |
| **Graph-based** | Complex workflows with conditionals | Full orchestration |

### Conceptual Code Structure

```python
from agent_framework import Agent, Workflow

# Define specialized agents
search_agent = Agent(
    name="SearchAgent",
    instructions="Search YouTube for videos about the given topic",
    tools=[youtube_search_tool]
)

transcript_agent = Agent(
    name="TranscriptAgent",
    instructions="Fetch and summarize YouTube video transcripts",
    tools=[transcript_tool, summarize_tool]
)

orchestrator = Agent(
    name="Orchestrator",
    instructions="""You coordinate research tasks:
    1. Use SearchAgent to find relevant videos
    2. Use TranscriptAgent (concurrently) for each video
    3. Synthesize all summaries into a final answer""",
    agents=[search_agent, transcript_agent]  # Sub-agents
)

# Or use graph-based workflow for more control
workflow = Workflow()
workflow.add_node("search", search_agent)
workflow.add_node("transcripts", transcript_agent, parallel=True)
workflow.add_node("synthesize", synthesize_function)
workflow.add_edge("search", "transcripts")
workflow.add_edge("transcripts", "synthesize")
```

### Updated Implementation Phases

#### Phase 1: Single Agent (Learn the basics)
- [ ] Simple transcript fetch + summarize agent
- [ ] Understand Agent Framework fundamentals

#### Phase 2: Add Search Agent
- [ ] Create YouTube search tool
- [ ] Build Search Agent
- [ ] Manual orchestration (call search, then transcript)

#### Phase 3: Multi-Agent Orchestration
- [ ] Create Orchestrator agent
- [ ] Implement concurrent transcript fetching
- [ ] Aggregate results into synthesized answer

#### Phase 4: Advanced Patterns
- [ ] Add caching (don't re-fetch same videos)
- [ ] Error handling (video has no transcript)
- [ ] Human-in-the-loop (approve search results before fetching)

### This Makes Great Blog Content!

Your blog post could follow this progression:
1. **Part 1**: Single agent basics
2. **Part 2**: Adding a second agent
3. **Part 3**: Orchestration patterns
4. **Part 4**: Production considerations

---

## 7. Learning Path Recommendation

### Week 1: Foundations
1. **Read**: [Microsoft Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)
2. **Do**: Complete the [Quick Start Tutorial](https://learn.microsoft.com/en-us/agent-framework/tutorials/quick-start)
3. **Explore**: [Getting Started Samples](https://github.com/microsoft/agent-framework/tree/main/python/samples/getting_started)

### Week 2: Single Agent + Tools
1. **Study**: How to create custom tools in Agent Framework
2. **Build**: Transcript Agent with youtube-transcript-api
3. **Learn**: Tool design patterns

### Week 3: Multi-Agent Patterns
1. **Study**: [Workflow documentation](https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/overview)
2. **Build**: Search Agent + Transcript Agent
3. **Learn**: Orchestration patterns (sequential, concurrent)

### Week 4: Full System
1. **Build**: Orchestrator that coordinates both agents
2. **Add**: Caching, error handling
3. **Test**: End-to-end with real queries

### Week 5: Polish & Share
1. **Refine**: Add UI and error handling
2. **Write**: Blog post
3. **Share**: Open source the project

---

## 7. Blog Post Outline

### Title Ideas
- "From AutoGen to Agent Framework: Building a YouTube Knowledge Base with Microsoft's Unified Agent Platform"
- "Hands-On with Microsoft Agent Framework: A Practical Guide for Enterprise Developers"
- "Building an AI Research Assistant with Azure and Microsoft Agent Framework"

### Suggested Structure

1. **Introduction**
   - The agent framework landscape in 2025
   - Why Microsoft unified AutoGen and Semantic Kernel

2. **What is Microsoft Agent Framework?**
   - Key concepts
   - Comparison to alternatives

3. **Hands-On: Building a YouTube Transcript Assistant**
   - Architecture overview
   - Step-by-step implementation
   - Code samples

4. **Lessons Learned**
   - What worked well
   - Gotchas and tips

5. **Conclusion**
   - When to use this framework
   - Future directions

---

## 8. Alternative Approaches

### If You Want to Compare Frameworks

Consider building the same project with:
1. **Microsoft Agent Framework** (recommended primary)
2. **LangGraph** (popular alternative)
3. **CrewAI** (for multi-agent comparison)

This would make excellent blog content showing trade-offs.

### Local-First Development

For faster iteration without Azure costs:
- Use **Ollama** for local LLMs
- Use **ChromaDB** for local vector storage
- Use **OpenAI API** directly (with API key)

Then migrate to Azure for production.

---

## 9. Development Environment

### Tools & Stack

| Tool | Purpose |
|------|---------|
| **uv** | Fast Python package manager (replaces pip/venv) |
| **DevContainer** | Consistent development environment |
| **Ruff** | Linting and formatting |
| **pytest** | Testing framework |
| **mypy** | Static type checking |

### Project Structure (Agent-Focused)

```
youtube-agent/
├── .devcontainer/
│   ├── devcontainer.json
│   └── Dockerfile
├── src/
│   └── youtube_agent/
│       ├── agents/          # Agent definitions (Search, Transcript, Orchestrator)
│       ├── tools/           # Tools agents can use (search, fetch, summarize)
│       └── models/          # Data models, config, Pydantic schemas
├── tests/
├── pyproject.toml
├── .env.example
└── Claude.md                # Coding style guide
```

**Why not DDD?** Agents are about behaviour and orchestration, not rich domain entities.

### Quick Start (with DevContainer)

1. **Clone and open in VS Code**
   ```bash
   git clone <repo-url>
   code youtube-agent
   ```

2. **Reopen in Container** (VS Code will prompt, or use Command Palette)

3. **Dependencies install automatically** via `uv sync`

4. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

### Quick Start (without DevContainer)

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup
git clone <repo-url>
cd youtube-agent

# Create venv and install dependencies
uv sync

# Activate environment
source .venv/bin/activate

# Set up environment
cp .env.example .env
# Edit .env with your API keys
```

### Common Commands

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov

# Type checking
uv run mypy src

# Linting
uv run ruff check src tests

# Format code
uv run ruff format src tests

# Add a dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>
```

---

## Sources

### Microsoft Agent Framework
- [Visual Studio Magazine - Semantic Kernel + AutoGen](https://visualstudiomagazine.com/articles/2025/10/01/semantic-kernel-autogen--open-source-microsoft-agent-framework.aspx)
- [Microsoft Learn - Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)
- [Azure Blog - Introducing Microsoft Agent Framework](https://azure.microsoft.com/en-us/blog/introducing-microsoft-agent-framework/)
- [Semantic Kernel Blog](https://devblogs.microsoft.com/semantic-kernel/semantic-kernel-and-microsoft-agent-framework/)

### Industry Analysis
- [Turing - AI Agent Frameworks Comparison](https://www.turing.com/resources/ai-agent-frameworks)
- [IBM Developer - Comparing AI Agent Frameworks](https://developer.ibm.com/articles/awb-comparing-ai-agent-frameworks-crewai-langgraph-and-beeai/)
- [Medium - Agent Framework Landscape 2025](https://medium.com/@hieutrantrung.it/the-ai-agent-framework-landscape-in-2025-what-changed-and-what-matters-3cd9b07ef2c3)

### Azure & RAG
- [Microsoft Learn - RAG Overview](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)
- [InfoQ - Azure AI Search Agentic Retrieval](https://www.infoq.com/news/2025/05/azure-ai-search-agent-retrieval/)
- [Pondhouse Data - Azure AI Search RAG Tutorial](https://www.pondhouse-data.com/blog/rag-with-azure-ai-search)

### YouTube Transcripts
- [PyPI - youtube-transcript-api](https://pypi.org/project/youtube-transcript-api/)
- [GitHub - youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)

### Vector Databases
- [The Data Quarry - What makes each vector DB different](https://thedataquarry.com/blog/vector-db-1/)
- [MyScale - Chroma vs Qdrant vs LanceDB](https://www.myscale.com/blog/milvus-alternatives-chroma-qdrant-lancedb/)
- [Firecrawl - Best Vector Databases 2025](https://www.firecrawl.dev/blog/best-vector-databases-2025)

### Multi-Agent Orchestration
- [Microsoft Learn - Workflows Overview](https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/overview)
- [Microsoft Learn - Orchestrations](https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/orchestrations/overview)
- [Semantic Kernel Blog - Multi-Agent Orchestration](https://devblogs.microsoft.com/semantic-kernel/unlocking-enterprise-ai-complexity-multi-agent-orchestration-with-the-microsoft-agent-framework/)
- [Workflow Samples](https://github.com/microsoft/agent-framework/tree/main/python/samples/getting_started/workflows)

### YouTube Search
- [youtube-search-python (PyPI)](https://pypi.org/project/youtube-search-python/)
- [youtube-search-python (GitHub)](https://github.com/alexmercerind/youtube-search-python)
