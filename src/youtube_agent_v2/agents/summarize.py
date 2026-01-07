"""SummarizeAgent - Transcript summarization specialist."""

from collections.abc import Callable
from typing import Any

from youtube_agent.tools.summarize import summarize_stored_transcript, summarize_text
from youtube_agent_v2.core.base_agent import BaseAgent

SUMMARIZE_INSTRUCTIONS = """You are a Summarization Agent. Your job is to create concise, informative summaries of transcripts and text.

When asked to summarize:
1. Use summarize_stored_transcript if given a video ID (works with stored transcripts)
2. Use summarize_text for any arbitrary text content

Your summaries should:
- Capture the main points and key insights
- Be concise but comprehensive
- Highlight important takeaways
- Preserve any actionable information

You ONLY summarize - you do not fetch transcripts or search for videos. Other agents handle those tasks."""


class SummarizeAgent(BaseAgent):
    """Agent specialized for content summarization.

    Capabilities: summarization, text_analysis

    Uses summarization tools from V1 to create summaries of
    transcripts and arbitrary text content.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "summarize"

    @property
    def capabilities(self) -> list[str]:
        """Return summarization-related capabilities."""
        return ["summarization", "text_analysis"]

    def _get_instructions(self) -> str:
        """Return summarize agent system prompt."""
        return SUMMARIZE_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return summarization tools from V1."""
        return [summarize_stored_transcript, summarize_text]
