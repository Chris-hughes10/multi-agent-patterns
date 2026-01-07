"""TranscriptAgent - YouTube transcript fetching and storage specialist."""

from collections.abc import Callable
from typing import Any

from youtube_agent.tools.transcript import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
    store_video_transcript,
)
from youtube_agent_v2.core import BaseAgent, Task, TaskResult

TRANSCRIPT_INSTRUCTIONS = """You are a Transcript Agent. Your job is to fetch and manage YouTube video transcripts.

When asked to work with transcripts:
1. Use fetch_video_transcript to get a transcript (checks cache first)
2. Use store_video_transcript to explicitly save a transcript
3. Use lookup_stored_transcript to retrieve a saved transcript by ID
4. Use list_stored_transcripts to see all stored transcripts

You handle transcript fetching and storage - you do NOT summarize. The SummarizeAgent handles summarization.

Tips:
- Transcripts are automatically cached when fetched
- Video IDs look like: dQw4w9WgXcQ (11 characters)
- You can accept both full URLs and video IDs"""


class TranscriptAgent(BaseAgent):
    """Agent specialized for YouTube transcript operations.

    Capabilities: transcript_fetch, transcript_storage

    Uses transcript tools from V1 to fetch, store, and retrieve
    video transcripts with automatic caching.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "transcript"

    @property
    def capabilities(self) -> list[str]:
        """Return transcript-related capabilities."""
        return ["transcript_fetch", "transcript_storage"]

    def _get_instructions(self) -> str:
        """Return transcript agent system prompt."""
        return TRANSCRIPT_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return transcript tools from V1."""
        return [
            fetch_video_transcript,
            store_video_transcript,
            lookup_stored_transcript,
            list_stored_transcripts,
        ]

    async def execute(self, task: Task) -> TaskResult:
        """Execute transcript task with optional auto-summarization.

        If task.context contains 'auto_summarize': True, spawns a
        sub-task for the SummarizeAgent after fetching the transcript.

        :param task: Task to execute
        :return: TaskResult with transcript data
        """
        # Execute the base transcript operation
        result = await super().execute(task)

        # Check if we should spawn a summarization sub-task
        if result.success and task.context.get("auto_summarize"):
            # Extract video_id from context or try to parse from result
            video_id = task.context.get("video_id")
            if video_id:
                summary_task = self.create_subtask(
                    parent_task=task,
                    description=f"Summarize the transcript for video {video_id}",
                    required_capabilities=["summarization"],
                    additional_context={"video_id": video_id},
                )
                await self.submit_task_async(summary_task)

        return result
