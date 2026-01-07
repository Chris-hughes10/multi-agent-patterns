"""SummarizeAgent - Transcript summarization specialist."""

import asyncio
from collections.abc import Callable
from typing import Any

from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.summarizer import TranscriptSummarizer
from youtube_agent.tools.summarize import summarize_stored_transcript, summarize_text
from youtube_agent_v2.core.base_agent import BaseAgent
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult
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

    @property
    def description(self) -> str:
        """Return description for intent routing."""
        return (
            "I summarize transcripts and text content. "
            "I create concise summaries with key points but do not search or fetch transcripts."
        )

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

    async def execute_autonomous(
        self,
        goal: str,
        state: dict[str, Any],
    ) -> HandoffResult | PartialResult:
        """Summarize content and reason about next steps.

        SummarizeAgent is typically the last step in a research chain,
        unless the goal mentions writing/exporting to a file.

        :param goal: Original user request
        :param state: Accumulated state from previous agents
        :return: HandoffResult (complete or handoff) or PartialResult on error
        """
        # Get transcripts from state
        transcript_data = state.get("transcript", {})
        transcripts = transcript_data.get("transcripts", [])

        if not transcripts:
            # Check for single transcript text in state
            text = state.get("text")
            if not text:
                return PartialResult(
                    error="No transcripts or text found in state to summarize",
                    partial_data=state,
                )
            transcripts = [{"text": text, "title": "Unknown", "video_id": None}]

        try:
            summarizer = TranscriptSummarizer()
            summaries = []

            for t in transcripts:
                # Include goal context for focused summarization via system prompt
                focus_prompt = (
                    f"Focus your summary on information relevant to: {goal}\n"
                    "Extract key details that address the user's specific question."
                )
                summary = await summarizer.summarize(
                    transcript_text=t["text"],
                    video_title=t.get("title"),
                    system_prompt=focus_prompt,
                )
                summaries.append({
                    "video_id": t.get("video_id"),
                    "title": t.get("title"),
                    "summary": summary,
                })

            output = {
                "summaries": summaries,
                "count": len(summaries),
                "goal": goal,
            }

            # Reason about what's needed next based on the goal
            goal_lower = goal.lower()
            needs_write = any(
                kw in goal_lower
                for kw in ["write", "save", "export", "file", "markdown", "document"]
            )

            if needs_write:
                return HandoffResult.handoff(
                    intent="Write these summaries to a markdown file",
                    state={**state, "summarize": output},
                )

            # Summarization is usually the final step
            return HandoffResult.complete(output)

        except Exception as e:
            return PartialResult(
                error=f"Summarization failed: {e}",
                partial_data=state,
            )
