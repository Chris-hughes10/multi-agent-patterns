"""TranscriptAgent - YouTube transcript fetching and storage specialist."""

import asyncio
import re
from collections.abc import Callable
from typing import Any

from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.youtube import extract_video_id, fetch_transcript
from youtube_agent.tools.transcript import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
    store_video_transcript,
)
from youtube_agent_v2.core import BaseAgent, Task, TaskResult, TaskStatus
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult

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

    Uses transcript services directly for DAG execution,
    returning structured data that can be used for variable resolution.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "transcript"

    @property
    def capabilities(self) -> list[str]:
        """Return transcript-related capabilities."""
        return ["transcript_fetch", "transcript_storage"]

    @property
    def description(self) -> str:
        """Return description for intent routing."""
        return (
            "I fetch transcripts and captions from YouTube videos. "
            "I get the spoken words but do not search or summarize."
        )

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
        """Execute transcript task and return structured results.

        Overrides base execute() to return structured data suitable
        for DAG variable resolution (e.g., $transcript_1.text).

        :param task: Task to execute
        :return: TaskResult with structured transcript data
        """
        task.status = TaskStatus.RUNNING

        try:
            # Extract video_id from task
            video_id = self._extract_video_id(task)

            # Check storage first
            storage = TranscriptStorage()
            stored = await asyncio.to_thread(storage.load, video_id)

            if stored:
                # Return cached transcript
                output = {
                    "video_id": video_id,
                    "title": stored.metadata.title or "Unknown",
                    "text": stored.transcript.full_text,
                    "cached": True,
                }
            else:
                # Fetch from YouTube
                result = await fetch_transcript(video_id)

                # Save to storage
                await asyncio.to_thread(storage.save, result)

                output = {
                    "video_id": video_id,
                    "title": result.metadata.title or "Unknown",
                    "text": result.transcript.full_text,
                    "cached": False,
                }

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
        """Fetch transcripts and reason about next steps.

        TranscriptAgent typically receives videos from SearchAgent and
        hands off to SummarizeAgent if summarization is needed.

        :param goal: Original user request
        :param state: Accumulated state from previous agents
        :return: HandoffResult (complete or handoff) or PartialResult on error
        """
        # Get videos from state (from previous search) or extract video_id from goal
        videos = state.get("videos", [])
        video_id = state.get("video_id")

        if not videos and not video_id:
            # Try to extract video_id from goal
            try:
                video_id = self._extract_video_id_from_goal(goal)
            except ValueError:
                return PartialResult(
                    error="No video ID found in state or goal",
                    partial_data=state,
                )

        try:
            storage = TranscriptStorage()
            transcripts = []

            if video_id:
                # Single video
                output = await self._fetch_single_transcript(storage, video_id)
                transcripts.append(output)
            else:
                # Multiple videos from search - fetch first few
                for video in videos[:3]:  # Limit to 3 for efficiency
                    vid = video.get("video_id") or video
                    if isinstance(vid, str):
                        output = await self._fetch_single_transcript(storage, vid)
                        transcripts.append(output)

            transcript_data = {
                "transcripts": transcripts,
                "count": len(transcripts),
            }

            # Reason about what's needed next based on the goal
            goal_lower = goal.lower()
            needs_summary = any(
                kw in goal_lower
                for kw in [
                    "summarize",
                    "summary",
                    "key points",
                    "main ideas",
                    "analyze",
                    "extract",
                    "temperature",
                    "cooking",
                    "how to",
                    "instructions",
                ]
            )

            if needs_summary:
                return HandoffResult.handoff(
                    intent="Summarize these transcripts focusing on the user's query",
                    state={**state, "transcript": transcript_data},
                )

            # Goal is satisfied with just transcripts
            return HandoffResult.complete(transcript_data)

        except Exception as e:
            return PartialResult(
                error=f"Transcript fetch failed: {e}",
                partial_data=state,
            )

    async def _fetch_single_transcript(
        self,
        storage: TranscriptStorage,
        video_id: str,
    ) -> dict[str, Any]:
        """Fetch a single transcript and return structured data.

        :param storage: TranscriptStorage instance
        :param video_id: Video ID to fetch
        :return: Structured transcript data
        """
        stored = await asyncio.to_thread(storage.load, video_id)

        if stored:
            return {
                "video_id": video_id,
                "title": stored.metadata.title or "Unknown",
                "text": stored.transcript.full_text,
                "cached": True,
            }

        result = await fetch_transcript(video_id)
        await asyncio.to_thread(storage.save, result)

        return {
            "video_id": video_id,
            "title": result.metadata.title or "Unknown",
            "text": result.transcript.full_text,
            "cached": False,
        }

    def _extract_video_id_from_goal(self, goal: str) -> str:
        """Extract video ID from natural language goal.

        :param goal: The user's goal
        :return: Extracted video ID
        :raises ValueError: If no video ID found
        """
        # Look for video ID pattern (11 alphanumeric chars)
        video_id_pattern = r"\b([a-zA-Z0-9_-]{11})\b"
        matches = re.findall(video_id_pattern, goal)
        if matches:
            for match in matches:
                try:
                    return extract_video_id(match)
                except ValueError:
                    continue

        # Try to extract from URL in goal
        url_pattern = r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})"
        match = re.search(url_pattern, goal)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract video ID from goal: {goal[:100]}")

    def _extract_video_id(self, task: Task) -> str:
        """Extract video ID from task description or context.

        :param task: The task to extract video ID from
        :return: Video ID string
        :raises ValueError: If no video ID can be extracted
        """
        # Check context first
        if "video_id" in task.context:
            return extract_video_id(task.context["video_id"])

        # Try to extract from description using patterns
        desc = task.description

        # Look for video ID pattern (11 alphanumeric chars)
        video_id_pattern = r"\b([a-zA-Z0-9_-]{11})\b"
        matches = re.findall(video_id_pattern, desc)
        if matches:
            # Return the first valid-looking video ID
            for match in matches:
                try:
                    return extract_video_id(match)
                except ValueError:
                    continue

        # Try to extract from URL in description
        url_pattern = r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})"
        match = re.search(url_pattern, desc)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract video ID from task: {task.description[:100]}")
