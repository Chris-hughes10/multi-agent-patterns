"""SearchAgent - YouTube video search specialist."""

import re
from collections.abc import Callable
from typing import Any

from youtube_agent.infra.client import get_chat_client
from youtube_agent.services.youtube import search_youtube
from youtube_agent.tools.search import search_youtube_structured
from youtube_agent_v2.core.base_agent import BaseAgent
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult
from youtube_agent_v2.core.models.task import Task, TaskResult, TaskStatus

SEARCH_INSTRUCTIONS = """You are a YouTube Search Agent. Your job is to find relevant YouTube videos based on user queries.

When asked to search:
1. Use the search_youtube_structured tool to find videos
2. The tool returns JSON with the search results
3. Return the JSON results directly - do not reformat them

You ONLY search - you do not fetch transcripts or summarize. Other agents handle those tasks.

The results contain video_id fields that other agents can use to fetch transcripts."""


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
        # Extract query from state or goal
        query = state.get("query")
        if not query:
            query = await self._extract_query_from_goal(goal)
        max_results = state.get("max_results", 5)

        try:
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

            # Reason about what's needed next based on the goal
            goal_lower = goal.lower()
            needs_transcript = any(
                kw in goal_lower
                for kw in ["transcript", "text", "words", "said", "spoken", "captions"]
            )
            needs_summary = any(
                kw in goal_lower
                for kw in ["summarize", "summary", "key points", "main ideas", "analyze"]
            )

            if needs_transcript or needs_summary:
                # Goal needs more than search - hand off
                intent = "Get transcripts for these videos"
                if needs_summary:
                    intent += " and summarize them"

                return HandoffResult.handoff(
                    intent=intent,
                    state={**state, "search": output, "videos": output["results"]},
                )

            # Goal is satisfied with just search results
            return HandoffResult.complete(output)

        except Exception as e:
            return PartialResult(error=f"Search failed: {e}", partial_data=state)

    async def _extract_query_from_goal(self, goal: str) -> str:
        """Extract search query from natural language goal using LLM.

        Uses a small LLM call to intelligently extract the core search
        terms from a complex natural language request.

        :param goal: The user's goal
        :return: Extracted search query
        """
        prompt = f"""Extract a YouTube search query from this user request.

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
