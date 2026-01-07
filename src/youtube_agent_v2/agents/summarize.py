"""SummarizeAgent - Transcript summarization specialist."""

import asyncio
from collections.abc import Callable
from typing import Any

from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.summarizer import TranscriptSummarizer
from youtube_agent.tools.summarize import summarize_stored_transcript, summarize_text
from youtube_agent_v2.core.base_agent import BaseAgent
from youtube_agent_v2.core.models.task import Task, TaskResult, TaskStatus

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

    Uses summarization services directly for DAG execution,
    returning structured data that can be used for variable resolution.
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

    async def execute(self, task: Task) -> TaskResult:
        """Execute summarization task and return structured results.

        Overrides base execute() to return structured data suitable
        for DAG variable resolution (e.g., $summarize_1.summary).

        :param task: Task to execute
        :return: TaskResult with structured summary data
        """
        task.status = TaskStatus.RUNNING

        try:
            # Get text and optional context from task
            text = task.context.get("text")
            video_id = task.context.get("video_id")
            title = task.context.get("title")

            summarizer = TranscriptSummarizer()

            if video_id and not text:
                # Summarize stored transcript
                storage = TranscriptStorage()
                stored = await asyncio.to_thread(storage.load, video_id)
                if stored is None:
                    task.status = TaskStatus.FAILED
                    return TaskResult(
                        success=False,
                        error=f"No stored transcript found for video ID: {video_id}",
                    )

                # Use cached summary if available
                if stored.summary:
                    output = {
                        "video_id": video_id,
                        "title": stored.metadata.title or "Unknown",
                        "summary": stored.summary,
                        "cached": True,
                    }
                else:
                    summary = await summarizer.summarize(
                        transcript_text=stored.transcript.full_text,
                        video_title=stored.metadata.title,
                    )
                    output = {
                        "video_id": video_id,
                        "title": stored.metadata.title or "Unknown",
                        "summary": summary,
                        "cached": False,
                    }
            elif text:
                # Summarize provided text
                summary = await summarizer.summarize(
                    transcript_text=text,
                    video_title=title,
                )
                output = {
                    "video_id": video_id,
                    "title": title or "Unknown",
                    "summary": summary,
                    "cached": False,
                }
            else:
                # No text provided - try to extract from description
                task.status = TaskStatus.FAILED
                return TaskResult(
                    success=False,
                    error="No text or video_id provided for summarization",
                )

            task.status = TaskStatus.COMPLETED
            return TaskResult(success=True, data=output)

        except Exception as e:
            task.status = TaskStatus.FAILED
            return TaskResult(success=False, error=str(e))
