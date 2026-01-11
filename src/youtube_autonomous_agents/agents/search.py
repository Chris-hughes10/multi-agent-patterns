"""SearchAgent - YouTube video search specialist."""

import logging
import re
from collections.abc import Callable
from typing import Any

from youtube_agent_orchestrator.infra.client import get_chat_client
from youtube_agent_orchestrator.services.youtube import search_youtube
from youtube_agent_orchestrator.tools.search import search_youtube_structured
from youtube_autonomous_agents.agents.base import BaseAgent
from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult
from youtube_autonomous_agents.models.task import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)

SEARCH_INSTRUCTIONS = """You are a YouTube Search Agent. Your job is to find relevant YouTube videos based on user queries.

When asked to search:
1. Use the search_youtube_structured tool to find videos
2. The tool returns JSON with the search results
3. Return the JSON results directly - do not reformat them

You ONLY search - you do not fetch transcripts or summarize. Other agents handle those tasks.

The results contain video_id fields that other agents can use to fetch transcripts."""


GOAL_REASONING_PROMPT = """You are helping decide if a user's goal is satisfied.

USER'S GOAL: "{goal}"

WHAT I DID: Searched YouTube and found these videos:
{video_titles}

QUESTION: Is the user's goal satisfied by just having these video links, or do they need more?

Consider:
- If they just want to find/discover videos → goal is SATISFIED
- If they want specific information FROM the videos (temperatures, steps, details, etc.) → need TRANSCRIPTS
- If they want analysis, summaries, or key points → need TRANSCRIPTS then SUMMARIZATION

Respond in this exact format:
SATISFIED: yes or no
NEXT_STEP: (only if not satisfied) describe what needs to happen next

Example responses:
SATISFIED: yes
NEXT_STEP: none

SATISFIED: no
NEXT_STEP: Get transcripts from these videos and extract the specific cooking temperatures and times the user asked for"""


QUERY_EXTRACTION_PROMPT = """Extract a YouTube search query from this user request.

User request: "{goal}"

Rules:
- Return ONLY the search query, nothing else
- Keep it concise (under 10 words ideally)
- Include the main topic and any specific details (equipment, channels, techniques)
- Remove meta-instructions like "summarize", "get transcripts", "I need to know"

Examples:
- "I want to cook a pork loin on a Kamado" → "pork loin kamado"
- "Find videos about Python async programming and summarize them" → "Python async programming"
- "Search for machine learning tutorials from 3Blue1Brown" → "machine learning 3Blue1Brown"

Search query:"""


class SearchAgent(BaseAgent):
    """Agent specialized for YouTube video search.

    Capabilities: youtube_search, video_discovery

    Uses the search_youtube service directly for DAG execution,
    returning structured data that can be used for variable resolution.
    """

    @property
    def name(self) -> str:
        """Return agent name."""
        return "search"

    @property
    def capabilities(self) -> list[str]:
        """Return search-related capabilities."""
        return ["youtube_search", "video_discovery"]

    @property
    def description(self) -> str:
        """Return description for intent routing."""
        return (
            "I search YouTube for videos matching queries. "
            "I find videos but do not fetch transcripts or summarize content."
        )

    def _get_instructions(self) -> str:
        """Return search agent system prompt."""
        return SEARCH_INSTRUCTIONS

    def _get_tools(self) -> list[Callable[..., Any]]:
        """Return search tools from V1."""
        return [search_youtube_structured]

    async def execute(self, task: Task) -> TaskResult:
        """Execute a search task and return structured results.

        Overrides base execute() to return structured data suitable
        for DAG variable resolution (e.g., $search.results[0].video_id).

        :param task: Task to execute
        :return: TaskResult with structured search data
        """
        task.status = TaskStatus.RUNNING

        try:
            # Extract query from task description or context
            query = self._extract_query(task)
            max_results = task.context.get("max_results", 5)

            # Call search service directly
            results = await search_youtube(query, max_results)

            # Build structured output
            output = {
                "query": query,
                "count": len(results),
                "results": [
                    {
                        "video_id": video.video_id,
                        "title": video.title,
                        "channel": video.channel,
                        "duration": video.duration,
                        "view_count": video.view_count,
                        "published_time": video.published_time,
                    }
                    for video in results
                ],
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
        """Execute search and reason about next steps.

        Search is typically the first step in a research chain. After
        searching, we check if the goal requires transcripts or summarization.

        :param goal: Original user request
        :param state: Accumulated state from previous agents
        :return: HandoffResult (complete or handoff) or PartialResult on error
        """
        # Check if we already have videos from parallel_results (join task recovery)
        # This handles cases where a join task is misrouted to search
        if "parallel_results" in state:
            parallel_results = state["parallel_results"]
            # Interleave videos from different searches to ensure diversity
            # (e.g., get 1 from Fork & Embers, 1 from Chuds BBQ, etc.)
            video_lists = [
                result["results"]
                for result in parallel_results
                if isinstance(result, dict) and "results" in result
            ]
            all_videos = self._interleave_videos(video_lists)
            if all_videos:
                logger.info(
                    "Found %d videos in parallel_results, passing through (skipping search)",
                    len(all_videos),
                )
                output = {
                    "query": "(from parallel searches)",
                    "count": len(all_videos),
                    "results": all_videos,
                }
                # Reason about goal with existing results
                reasoning = await self._reason_about_goal(goal, output)
                if reasoning["satisfied"]:
                    return HandoffResult.complete(output)
                else:
                    return HandoffResult.handoff(
                        intent=reasoning["next_step"],
                        state={**state, "search": output, "videos": all_videos},
                    )

        # Extract query from state or goal
        query = state.get("query")
        if not query:
            query = await self._extract_query_from_goal(goal)
        max_results = state.get("max_results", 5)

        try:
            logger.info("Searching YouTube for: %s", query)
            results = await search_youtube(query, max_results)

            output = {
                "query": query,
                "count": len(results),
                "results": [
                    {
                        "video_id": video.video_id,
                        "title": video.title,
                        "channel": video.channel,
                        "duration": video.duration,
                        "view_count": video.view_count,
                        "published_time": video.published_time,
                    }
                    for video in results
                ],
            }

            # Log found videos
            logger.info("Found %d videos:", len(results))
            for video in results[:5]:
                logger.info("  - [%s] %s (%s)", video.video_id, video.title, video.channel)

            # If this is a parallel task, always complete with results
            # (the join task will continue the chain)
            if state.get("is_parallel_task"):
                logger.info("Parallel task - completing with results (join will continue chain)")
                return HandoffResult.complete(output)

            # Use LLM to reason about whether the goal is satisfied
            reasoning = await self._reason_about_goal(goal, output)

            if reasoning["satisfied"]:
                return HandoffResult.complete(output)
            else:
                return HandoffResult.handoff(
                    intent=reasoning["next_step"],
                    state={**state, "search": output, "videos": output["results"]},
                )

        except Exception as e:
            return PartialResult(error=f"Search failed: {e}", partial_data=state)

    async def _reason_about_goal(
        self, goal: str, search_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Use LLM to reason about whether the goal is satisfied.

        :param goal: Original user request
        :param search_results: The search results we found
        :return: Dict with 'satisfied' (bool) and 'next_step' (str if not satisfied)
        """
        video_titles = [r["title"] for r in search_results.get("results", [])[:3]]
        video_titles_formatted = "\n".join(f"- {title}" for title in video_titles)

        prompt = GOAL_REASONING_PROMPT.format(
            goal=goal,
            video_titles=video_titles_formatted,
        )

        try:
            client = get_chat_client()
            response = await client.get_response(prompt)
            text = response.text.strip()

            # Parse the response
            text_lower = text.lower()
            satisfied = "satisfied: yes" in text_lower or "satisfied:yes" in text_lower

            next_step = "Get transcripts for these videos and analyze them"
            if "NEXT_STEP:" in text:
                next_step = text.split("NEXT_STEP:")[-1].strip()
                if next_step.lower() == "none":
                    next_step = ""

            return {"satisfied": satisfied, "next_step": next_step}

        except Exception:
            # On error, default to handing off (safer to do more work than less)
            return {
                "satisfied": False,
                "next_step": "Get transcripts for these videos to extract detailed information",
            }

    async def _extract_query_from_goal(self, goal: str) -> str:
        """Extract search query from natural language goal using LLM.

        Uses a small LLM call to intelligently extract the core search
        terms from a complex natural language request.

        :param goal: The user's goal
        :return: Extracted search query
        """
        prompt = QUERY_EXTRACTION_PROMPT.format(goal=goal)

        try:
            client = get_chat_client()
            response = await client.get_response(prompt)
            query = response.text.strip().strip('"').strip("'")
            # Sanity check - if response is too long, it's probably not a query
            if len(query) > 100:
                return goal[:100]
            return query or goal[:100]
        except Exception:
            # Fallback to simple truncation if LLM fails
            return goal[:100]

    def _extract_query(self, task: Task) -> str:
        """Extract search query from task description or context.

        :param task: The task to extract query from
        :return: Search query string
        """
        # Check context first
        if "query" in task.context:
            return task.context["query"]

        # Try to extract from description
        desc = task.description.lower()

        # Common patterns
        patterns = [
            r"search (?:youtube )?for[:\s]+['\"]?([^'\"]+)['\"]?",
            r"find (?:youtube )?videos? (?:about|on|for)[:\s]+['\"]?([^'\"]+)['\"]?",
            r"search[:\s]+['\"]?([^'\"]+)['\"]?",
            r"query[:\s]+['\"]?([^'\"]+)['\"]?",
        ]

        for pattern in patterns:
            match = re.search(pattern, desc, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Fallback: use the whole description as query
        # Remove common prefixes
        query = task.description
        for prefix in ["search for", "find videos about", "search youtube for"]:
            if query.lower().startswith(prefix):
                query = query[len(prefix) :].strip()
                break

        return query

    def _interleave_videos(self, video_lists: list[list[dict]]) -> list[dict]:
        """Interleave videos from multiple search results for diversity.

        Instead of [A1, A2, A3, B1, B2, B3], produces [A1, B1, A2, B2, A3, B3].
        This ensures that when we fetch only N transcripts, we get videos
        from multiple searches rather than all from one.

        :param video_lists: List of video lists from different searches
        :return: Interleaved list of videos
        """
        if not video_lists:
            return []
        if len(video_lists) == 1:
            return video_lists[0]

        interleaved = []
        max_len = max(len(vl) for vl in video_lists)

        for i in range(max_len):
            for video_list in video_lists:
                if i < len(video_list):
                    interleaved.append(video_list[i])

        return interleaved
