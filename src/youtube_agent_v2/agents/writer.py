"""WriterAgent - Markdown file export specialist."""

import re
from collections.abc import Callable
from typing import Any

from youtube_agent.tools.writer import write_markdown_file, write_timestamped_markdown
from youtube_agent_v2.core.base_agent import BaseAgent
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult

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

    @property
    def description(self) -> str:
        """Return description for intent routing."""
        return (
            "I write and export content to markdown files. "
            "I save research results and summaries but do not search, fetch, or analyze."
        )

    def _get_instructions(self) -> str:
        """Return writer agent system prompt."""
        return WRITER_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return writer tools from V1."""
        return [write_markdown_file, write_timestamped_markdown]

    async def execute_autonomous(
        self,
        goal: str,
        state: dict[str, Any],
    ) -> HandoffResult | PartialResult:
        """Write content to file. Always completes (final step).

        WriterAgent is always the final step in a chain - it produces
        output files and returns.

        :param goal: Original user request
        :param state: Accumulated state from previous agents
        :return: HandoffResult (always complete) or PartialResult on error
        """
        # Get content to write from state
        summaries = state.get("summarize", {}).get("summaries", [])
        search_results = state.get("search", {})
        transcripts = state.get("transcript", {})

        try:
            # Build markdown content from accumulated state
            content = self._build_markdown_content(goal, summaries, search_results, transcripts)

            # Generate filename from goal
            filename_prefix = self._generate_filename_prefix(goal)

            # Write file with timestamp to avoid overwrites
            filepath = await write_timestamped_markdown(content, prefix=filename_prefix)

            return HandoffResult.complete({
                "filepath": filepath,
                "content_length": len(content),
                "goal": goal,
            })

        except Exception as e:
            return PartialResult(
                error=f"Write failed: {e}",
                partial_data=state,
            )

    def _build_markdown_content(
        self,
        goal: str,
        summaries: list[dict[str, Any]],
        search_results: dict[str, Any],
        transcripts: dict[str, Any],
    ) -> str:
        """Build markdown content from accumulated state.

        :param goal: The original user goal
        :param summaries: List of summary dicts from SummarizeAgent
        :param search_results: Search results from SearchAgent
        :param transcripts: Transcript data from TranscriptAgent
        :return: Formatted markdown string
        """
        lines = [f"# Research: {goal}", ""]

        if summaries:
            lines.append("## Summaries")
            lines.append("")
            for s in summaries:
                title = s.get("title", "Unknown")
                lines.append(f"### {title}")
                lines.append("")
                lines.append(s.get("summary", "No summary available"))
                lines.append("")

        if search_results.get("results"):
            lines.append("## Videos Found")
            lines.append("")
            for v in search_results["results"]:
                video_id = v.get("video_id", "")
                title = v.get("title", "Unknown")
                channel = v.get("channel", "Unknown")
                lines.append(f"- [{title}](https://youtube.com/watch?v={video_id}) by {channel}")
            lines.append("")

        if transcripts.get("transcripts"):
            lines.append("## Transcripts")
            lines.append("")
            for t in transcripts["transcripts"]:
                title = t.get("title", "Unknown")
                lines.append(f"### {title}")
                lines.append("")
                # Truncate long transcripts
                text = t.get("text", "")
                if len(text) > 2000:
                    text = text[:2000] + "...\n\n[Transcript truncated]"
                lines.append(text)
                lines.append("")

        return "\n".join(lines)

    def _generate_filename_prefix(self, goal: str) -> str:
        """Generate a filename prefix from the goal.

        :param goal: The user's goal
        :return: Sanitized filename prefix
        """
        # Take first few words, sanitize for filesystem
        words = re.sub(r"[^a-zA-Z0-9\s]", "", goal).split()[:4]
        return "_".join(words).lower() or "research"
