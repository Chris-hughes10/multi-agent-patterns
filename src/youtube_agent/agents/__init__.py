"""YouTube Agent multi-agent system.

This module provides a multi-agent system for YouTube research:
- SearchAgent: Find YouTube videos by topic
- TranscriptAgent: Fetch, store, and retrieve transcripts
- SummarizeAgent: Generate summaries from transcripts
- WriterAgent: Export content to markdown files
- Orchestrator: Coordinate all agents for research tasks
"""

from youtube_agent.agents.orchestrator import OrchestratorAgent, create_orchestrator
from youtube_agent.agents.search_agent import create_search_agent
from youtube_agent.agents.summarize_agent import create_summarize_agent
from youtube_agent.agents.transcript_agent import create_transcript_agent
from youtube_agent.agents.writer_agent import create_writer_agent

__all__ = [
    "create_search_agent",
    "create_transcript_agent",
    "create_summarize_agent",
    "create_writer_agent",
    "create_orchestrator",
    "OrchestratorAgent",
]
