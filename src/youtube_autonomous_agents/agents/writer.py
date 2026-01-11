"""WriterAgent - Markdown file export specialist."""

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from youtube_agent_orchestrator.infra.client import get_chat_client

if TYPE_CHECKING:
    from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent_orchestrator.tools.writer import write_markdown_file, write_timestamped_markdown
from youtube_autonomous_agents.agents.base import BaseAgent
from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult

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


CONTENT_BUILDING_PROMPT = """You are creating a clean, well-formatted markdown document.

USER'S GOAL: "{goal}"

RAW CONTENT FROM PREVIOUS AGENTS:
{summaries_input}

Your task:
1. Create a clean markdown document that addresses the user's goal
2. REMOVE any meta-commentary like "Saved to file", "Content ready to save", "File output", etc.
3. REMOVE any internal agent messages or instructions
4. Keep ONLY the actual useful content (facts, data, steps, techniques)
5. Organize with clear headers and bullet points
6. Keep the same information but remove the noise
7. IMPORTANT: Include video IDs (like fI86yXKlnQA) in the content when referencing specific videos

Output ONLY the clean markdown content, starting with a # header. Do not include any preamble or explanation."""


FILENAME_GENERATION_PROMPT = """Generate a short, descriptive filename for a markdown research document.

User's request: "{goal}"{topics_hint}

Rules:
- Return ONLY the filename prefix (no extension, no path)
- Use 2-4 words separated by underscores
- Be specific about the topic (e.g., "pork_loin_kamado_cooking" not "cooking_research")
- Use lowercase letters and underscores only
- No quotes or special characters

Example outputs:
- pork_loin_kamado_tips
- python_async_tutorial
- bbq_brisket_techniques

Filename:"""


class WriterAgent(BaseAgent):
    """Agent specialized for file export operations.

    Capabilities: file_export, markdown_writing

    Uses writer tools from V1 to export content to markdown files
    with support for custom filenames and timestamps.
    """

    def __init__(self, client: "AzureOpenAIChatClient | None" = None) -> None:
        """Initialize with optional chat client.

        :param client: Optional chat client for dependency injection
        """
        super().__init__()
        self._client = client or get_chat_client()

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

        # Get original request for better filename (goal might be a join_intent)
        original_request = state.get("original_request", goal)

        try:
            # Build markdown content from accumulated state using LLM reasoning
            content = await self._build_markdown_content(goal, summaries, search_results, transcripts)

            # Check if user specified an explicit filename in the request
            explicit_filename = self._extract_explicit_filename(original_request)
            if not explicit_filename:
                explicit_filename = self._extract_explicit_filename(goal)

            if explicit_filename:
                # Use the exact filename the user requested
                filepath = await write_markdown_file(content, explicit_filename)
            else:
                # Generate filename using LLM for meaningful names
                filename_prefix = await self._generate_filename_prefix_llm(original_request, summaries)
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

    async def _build_markdown_content(
        self,
        goal: str,
        summaries: list[dict[str, Any]],
        search_results: dict[str, Any],
        transcripts: dict[str, Any],
    ) -> str:
        """Build markdown content using LLM to synthesize clean output.

        Uses LLM reasoning to produce a focused document based on the goal,
        filtering out meta-commentary and internal messages.

        :param goal: The original user goal
        :param summaries: List of summary dicts from SummarizeAgent
        :param search_results: Search results from SearchAgent
        :param transcripts: Transcript data from TranscriptAgent
        :return: Formatted markdown string
        """
        # Build a title lookup from search results (video_id -> title)
        title_lookup = {}
        video_links = []
        if search_results.get("results"):
            for v in search_results["results"]:
                vid = v.get("video_id")
                title = v.get("title", "Unknown")
                channel = v.get("channel", "Unknown")
                if vid:
                    title_lookup[vid] = title
                    video_links.append(f"- [{title}](https://youtube.com/watch?v={vid}) by {channel}")

        # Build input for LLM
        summary_texts = []
        for s in summaries:
            video_id = s.get("video_id")
            title = s.get("title")
            if not title or title == "Unknown":
                title = title_lookup.get(video_id, "Unknown Video")
            summary_texts.append(f"### {title}\n{s.get('summary', 'No summary')}")

        summaries_input = "\n\n".join(summary_texts) if summary_texts else "No summaries available."

        prompt = CONTENT_BUILDING_PROMPT.format(
            goal=goal,
            summaries_input=summaries_input,
        )

        try:
            client = self._client
            response = await client.get_response(prompt)
            content = response.text.strip()

            # Append source videos section
            if video_links:
                content += "\n\n## Source Videos\n\n" + "\n".join(video_links)

            return content

        except Exception:
            # Fallback to basic formatting if LLM fails
            return self._build_fallback_content(goal, summaries, title_lookup, video_links, transcripts)

    def _build_fallback_content(
        self,
        goal: str,
        summaries: list[dict[str, Any]],
        title_lookup: dict[str, str],
        video_links: list[str],
        transcripts: dict[str, Any],
    ) -> str:
        """Build basic markdown content without LLM (fallback).

        :param goal: The original user goal
        :param summaries: List of summary dicts
        :param title_lookup: video_id -> title mapping
        :param video_links: List of formatted video links
        :param transcripts: Transcript data
        :return: Formatted markdown string
        """
        lines = [f"# {goal}", ""]

        if summaries:
            for s in summaries:
                video_id = s.get("video_id")
                title = s.get("title")
                if not title or title == "Unknown":
                    title = title_lookup.get(video_id, "Unknown Video")
                lines.append(f"## {title}")
                lines.append("")
                lines.append(s.get("summary", "No summary available"))
                lines.append("")

        if video_links:
            lines.append("## Source Videos")
            lines.append("")
            lines.extend(video_links)
            lines.append("")

        # Only include transcripts if NO summaries exist
        if not summaries and transcripts.get("transcripts"):
            lines.append("## Raw Transcripts")
            lines.append("")
            for t in transcripts["transcripts"]:
                video_id = t.get("video_id")
                title = t.get("title")
                if not title or title == "Unknown":
                    title = title_lookup.get(video_id, "Unknown Video")
                lines.append(f"### {title}")
                lines.append("")
                text = t.get("text", "")
                if len(text) > 2000:
                    text = text[:2000] + "...\n\n[Transcript truncated]"
                lines.append(text)
                lines.append("")

        return "\n".join(lines)

    async def _generate_filename_prefix_llm(
        self,
        goal: str,
        summaries: list[dict[str, Any]],
    ) -> str:
        """Generate a meaningful filename prefix using LLM.

        :param goal: The user's goal/request
        :param summaries: Summaries to help determine topic
        :return: Sanitized filename prefix
        """
        # Get topic hints from summaries
        topics = []
        for s in summaries[:3]:
            title = s.get("title", "")
            if title and title != "Unknown":
                topics.append(title)

        topics_hint = f"\nVideo topics: {', '.join(topics)}" if topics else ""

        prompt = FILENAME_GENERATION_PROMPT.format(
            goal=goal,
            topics_hint=topics_hint,
        )

        try:
            client = self._client
            response = await client.get_response(prompt)
            filename = response.text.strip().strip('"').strip("'").lower()

            # Sanitize: keep only alphanumeric and underscores
            filename = re.sub(r"[^a-z0-9_]", "_", filename)
            filename = re.sub(r"_+", "_", filename)  # Collapse multiple underscores
            filename = filename.strip("_")

            # Validate length
            if 3 <= len(filename) <= 50:
                return filename

        except Exception:
            pass

        # Fallback to simple extraction
        return self._generate_filename_prefix_simple(goal)

    def _generate_filename_prefix_simple(self, goal: str) -> str:
        """Generate a filename prefix from the goal (fallback).

        :param goal: The user's goal
        :return: Sanitized filename prefix
        """
        # Take first few words, sanitize for filesystem
        words = re.sub(r"[^a-zA-Z0-9\s]", "", goal).split()[:4]
        return "_".join(words).lower() or "research"

    def _extract_explicit_filename(self, text: str) -> str | None:
        """Extract an explicit filename from user request.

        Looks for patterns like:
        - "save to filename.md"
        - "save the results to filename.md"
        - "write to filename.md"
        - "export to filename.md"

        :param text: User request text
        :return: Filename if found, None otherwise
        """
        if not text:
            return None

        # Pattern to match "save/write/export to <filename>.md"
        patterns = [
            r"(?:save|write|export)(?:\s+(?:the\s+)?(?:results?|output|content))?\s+(?:to|as)\s+([a-zA-Z0-9_\-]+\.md)",
            r"(?:save|write|export)\s+(?:to|as)\s+([a-zA-Z0-9_\-]+\.md)",
            r"filename[:\s]+([a-zA-Z0-9_\-]+\.md)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                filename = match.group(1)
                # Remove .md extension if present (write_markdown_file adds it)
                if filename.endswith(".md"):
                    filename = filename[:-3]
                return filename

        return None
