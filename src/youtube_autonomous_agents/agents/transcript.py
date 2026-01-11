"""TranscriptAgent - YouTube transcript fetching and storage specialist."""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework.azure import AzureOpenAIChatClient

    from youtube_autonomous_agents.infra.registry import AgentRegistry

from youtube_agent_orchestrator.services.storage import TranscriptStorage
from youtube_agent_orchestrator.services.youtube import extract_video_id, fetch_transcript
from youtube_agent_orchestrator.tools.transcript import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
    store_video_transcript,
)
from youtube_autonomous_agents.agents.base import BaseAgent
from youtube_autonomous_agents.models import Task, TaskResult, TaskStatus
from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult

logger = logging.getLogger(__name__)

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


GOAL_REASONING_PROMPT = """You are helping decide if a user's goal is satisfied.

USER'S GOAL: "{goal}"

WHAT I DID: Fetched {transcript_count} transcript(s) from YouTube videos.
{preview}

QUESTION: Is the user's goal satisfied by just having these raw transcripts, or do they need more?

Consider:
- If they ONLY want the transcript text itself → goal is SATISFIED
- If they want specific information extracted (temperatures, steps, times, etc.) → need SUMMARIZATION first
- If they want key points, summaries, or answers to questions → need SUMMARIZATION first
- If they want to save/export AND need analysis → SUMMARIZE FIRST, then save (summarization must come before saving!)

IMPORTANT: If the goal mentions both "summarize" AND "save to file", the next step is SUMMARIZATION (the save comes after).

Respond in this exact format:
SATISFIED: yes or no
NEXT_STEP: (only if not satisfied) describe what needs to happen next - focus on ANALYSIS/SUMMARIZATION, not file saving

Example responses:
SATISFIED: yes
NEXT_STEP: none

SATISFIED: no
NEXT_STEP: Analyze these transcripts to extract the cooking temperatures, grill setup, and timing information the user asked for"""


VIDEO_SELECTION_PROMPT = """Select the {max_count} most relevant videos for this user's request.

USER'S REQUEST: "{goal}"

AVAILABLE VIDEOS:
{video_descriptions}

Select videos that best match what the user asked for. Prioritize videos from any channels the user mentioned by name.

Respond with ONLY the numbers of your choices, separated by commas (e.g., 1, 4, 7)"""


class TranscriptAgent(BaseAgent):
    """Agent specialized for YouTube transcript operations.

    Capabilities: transcript_fetch, transcript_storage

    Uses transcript services directly for DAG execution,
    returning structured data that can be used for variable resolution.
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        storage: TranscriptStorage | None = None,
        client: "AzureOpenAIChatClient | None" = None,
    ) -> None:
        """Initialize with registry and optional dependencies.

        :param registry: Registry for agent discovery and task submission
        :param storage: Optional TranscriptStorage instance for dependency injection
        :param client: Optional chat client for dependency injection
        """
        super().__init__(registry, client)
        self._storage = storage or TranscriptStorage()

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

    def _can_handle_intent(self, intent: str) -> bool:
        """Check if this agent can handle a natural language intent.

        Override to reject summarize/analyze intents - those should go to SummarizeAgent
        even if "transcript" appears in the text.

        :param intent: Natural language intent from handoff
        :return: True if this agent should handle the intent
        """
        intent_lower = intent.lower()

        # Reject summarize/analyze intents - those are for SummarizeAgent
        summarize_keywords = ["summarize", "summary", "key points", "analyze", "extract info"]
        if any(kw in intent_lower for kw in summarize_keywords):
            return False

        # Accept transcript-related intents
        transcript_keywords = ["transcript", "captions", "fetch", "get text", "spoken words"]
        return any(kw in intent_lower for kw in transcript_keywords)

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
            stored = await asyncio.to_thread(self._storage.load, video_id)

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
                await asyncio.to_thread(self._storage.save, result)

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

        # Check for parallel_results from fan-out (recovers videos if join was misrouted)
        if not videos and "parallel_results" in state:
            parallel_results = state["parallel_results"]
            logger.info("Extracting videos from parallel_results (%d results)", len(parallel_results))
            for result in parallel_results:
                if isinstance(result, dict) and "results" in result:
                    videos.extend(result["results"])
            if videos:
                logger.info("Recovered %d videos from parallel search results", len(videos))

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
            transcripts = []
            errors = []  # Track per-video errors for graceful degradation

            if video_id:
                # Single video
                logger.info("Fetching transcript for single video: %s", video_id)
                try:
                    output = await self._fetch_single_transcript(video_id)
                    logger.info("  Got transcript: %s (%d chars)", output.get("title", "Unknown"), len(output.get("text", "")))
                    transcripts.append(output)
                except Exception as e:
                    logger.warning("  Failed to fetch transcript: %s", e)
                    errors.append({"video_id": video_id, "error": str(e)})
            else:
                # Multiple videos from search - use LLM to select most relevant
                # Use original_request if available (contains user's channel preferences)
                selection_goal = state.get("original_request", goal)
                max_transcripts = state.get("max_transcripts", 5)
                selected_videos = await self._select_relevant_videos(videos, selection_goal, max_count=max_transcripts)
                logger.info("Selected %d most relevant videos from %d available", len(selected_videos), len(videos))
                for video in selected_videos:
                    vid = video.get("video_id") or video
                    # Preserve title from search results if available
                    search_title = video.get("title") if isinstance(video, dict) else None
                    if isinstance(vid, str):
                        logger.info("  Fetching: %s - %s", vid, search_title or "Unknown")
                        try:
                            output = await self._fetch_single_transcript(vid)
                            # Use search title if transcript title is missing
                            if search_title and (not output.get("title") or output.get("title") == "Unknown"):
                                output["title"] = search_title
                            logger.info("    Got %d chars", len(output.get("text", "")))
                            transcripts.append(output)
                        except Exception as e:
                            # Log error but continue with other videos (graceful degradation)
                            logger.warning("    Failed: %s", e)
                            errors.append({"video_id": vid, "error": str(e)})
                            continue

            # If no transcripts fetched at all, return partial result with errors
            if not transcripts and errors:
                return PartialResult(
                    error=f"Failed to fetch any transcripts: {errors}",
                    partial_data=state,
                )

            transcript_data = {
                "transcripts": transcripts,
                "errors": errors,  # Include errors so downstream agents are aware
                "count": len(transcripts),
            }

            # Use LLM to reason about whether the goal is satisfied
            reasoning = await self._reason_about_goal(goal, transcript_data)

            if reasoning["satisfied"]:
                return HandoffResult.complete(transcript_data)
            else:
                return HandoffResult.handoff(
                    intent=reasoning["next_step"],
                    state={**state, "transcript": transcript_data},
                )

        except Exception as e:
            return PartialResult(
                error=f"Transcript fetch failed: {e}",
                partial_data=state,
            )

    async def _reason_about_goal(
        self, goal: str, transcript_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Use LLM to reason about whether the goal is satisfied.

        :param goal: Original user request
        :param transcript_data: The transcripts we fetched
        :return: Dict with 'satisfied' (bool) and 'next_step' (str if not satisfied)
        """
        transcript_count = transcript_data.get("count", 0)
        # Get a preview of transcript content
        preview = ""
        if transcript_data.get("transcripts"):
            first = transcript_data["transcripts"][0]
            text = first.get("text", "")[:200]
            preview = f"Preview: {text}..."

        prompt = GOAL_REASONING_PROMPT.format(
            goal=goal,
            transcript_count=transcript_count,
            preview=preview,
        )

        try:
            client = self._client
            response = await client.get_response(prompt)
            text = response.text.strip()

            # Parse the response
            text_lower = text.lower()
            satisfied = "satisfied: yes" in text_lower or "satisfied:yes" in text_lower

            next_step = "Summarize these transcripts focusing on the user's query"
            if "NEXT_STEP:" in text:
                next_step = text.split("NEXT_STEP:")[-1].strip()
                if next_step.lower() == "none":
                    next_step = ""

            return {"satisfied": satisfied, "next_step": next_step}

        except Exception:
            # On error, default to handing off (safer to do more work than less)
            return {
                "satisfied": False,
                "next_step": "Summarize these transcripts to extract the information the user needs",
            }

    async def _select_relevant_videos(
        self,
        videos: list[dict[str, Any]],
        goal: str,
        max_count: int = 3,
    ) -> list[dict[str, Any]]:
        """Use LLM to select the most relevant videos for the user's goal.

        :param videos: List of video dicts with title, channel, video_id
        :param goal: The user's goal/request
        :param max_count: Maximum number of videos to select
        :return: List of selected video dicts
        """
        if len(videos) <= max_count:
            return videos

        # Build video list for the prompt
        video_descriptions = []
        for i, video in enumerate(videos):
            title = video.get("title", "Unknown")
            channel = video.get("channel", "Unknown")
            video_descriptions.append(f"{i + 1}. \"{title}\" by {channel}")

        prompt = VIDEO_SELECTION_PROMPT.format(
            max_count=max_count,
            goal=goal,
            video_descriptions="\n".join(video_descriptions),
        )

        try:
            client = self._client
            response = await client.get_response(prompt)
            text = response.text.strip()

            # Parse the numbers from the response
            import re
            numbers = re.findall(r"\d+", text)
            selected_indices = []
            for num in numbers:
                idx = int(num) - 1  # Convert to 0-indexed
                if 0 <= idx < len(videos) and idx not in selected_indices:
                    selected_indices.append(idx)
                if len(selected_indices) >= max_count:
                    break

            if selected_indices:
                selected = [videos[i] for i in selected_indices]
                logger.info(
                    "LLM selected videos: %s",
                    ", ".join(v.get("title", "?")[:40] for v in selected),
                )
                return selected

        except Exception as e:
            logger.warning("Video selection failed: %s, using first %d", e, max_count)

        # Fallback to first N videos
        return videos[:max_count]

    async def _fetch_single_transcript(
        self,
        video_id: str,
    ) -> dict[str, Any]:
        """Fetch a single transcript and return structured data.

        :param video_id: Video ID to fetch
        :return: Structured transcript data
        """
        stored = await asyncio.to_thread(self._storage.load, video_id)

        if stored:
            return {
                "video_id": video_id,
                "title": stored.metadata.title or "Unknown",
                "text": stored.transcript.full_text,
                "cached": True,
            }

        result = await fetch_transcript(video_id)
        await asyncio.to_thread(self._storage.save, result)

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
