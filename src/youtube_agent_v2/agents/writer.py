"""WriterAgent - Markdown file export specialist."""

from collections.abc import Callable
from typing import Any

from youtube_agent.tools.writer import write_markdown_file, write_timestamped_markdown
from youtube_agent_v2.core.base_agent import BaseAgent

WRITER_INSTRUCTIONS = """You are a Writer Agent. Your job is to export content to markdown files.

When asked to write or export:
1. Use write_markdown_file to write content to a specific filename
2. Use write_timestamped_markdown to create uniquely named files (avoids overwrites)

Best practices:
- Use descriptive filenames that reflect the content
- Use timestamped files for research notes or repeated operations
- Default output directory is 'output/' but can be customized
- Files automatically get .md extension if not provided

You ONLY write files - you do not fetch transcripts, search, or summarize. Other agents handle those tasks."""


class WriterAgent(BaseAgent):
    """Agent specialized for file export operations.

    Capabilities: file_export, markdown_writing

    Uses writer tools from V1 to export content to markdown files
    with support for custom filenames and timestamps.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "writer"

    @property
    def capabilities(self) -> list[str]:
        """Return writing-related capabilities."""
        return ["file_export", "markdown_writing"]

    def _get_instructions(self) -> str:
        """Return writer agent system prompt."""
        return WRITER_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return writer tools from V1."""
        return [write_markdown_file, write_timestamped_markdown]
