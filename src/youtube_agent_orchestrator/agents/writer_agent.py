"""Writer Agent - exports content to markdown files."""

import logging

from agent_framework import Agent

from youtube_agent_orchestrator.infra.client import get_chat_client, get_default_options
from youtube_agent_orchestrator.tools.writer import write_markdown_file, write_timestamped_markdown

logger = logging.getLogger("youtube_agent.writer_agent")

WRITER_AGENT_INSTRUCTIONS = """You are a Writer Agent. Your job is to export content to markdown files.

You can:
1. Write content to a specific markdown file
2. Write content to a timestamped file (to avoid overwrites)

When writing:
- Format content as clean, readable markdown
- Use appropriate headings, lists, and formatting
- Include metadata (date, source) when relevant
- Suggest meaningful filenames based on content

Output files are saved to the 'output' directory by default.

IMPORTANT: You write files exactly as requested. You do NOT generate new content -
the Orchestrator or other agents provide the content to write."""


def create_writer_agent() -> Agent:
    """Create a Writer Agent instance.

    :return: Configured Agent for writing markdown files
    """
    return Agent(
        client=get_chat_client(),
        name="WriterAgent",
        instructions=WRITER_AGENT_INSTRUCTIONS,
        tools=[
            write_markdown_file,
            write_timestamped_markdown,
        ],
        default_options=get_default_options(),
    )
