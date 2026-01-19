"""SummarizeAgent - Transcript summarization specialist."""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework.azure import AzureOpenAIChatClient

    from youtube_goal_agents.infra.registry import AgentRegistry

from youtube_agent_orchestrator.services.storage import TranscriptStorage
from youtube_agent_orchestrator.services.summarizer import TranscriptSummarizer
from youtube_agent_orchestrator.tools.summarize import summarize_stored_transcript, summarize_text
from youtube_goal_agents.agents.base import BaseAgent
from youtube_goal_agents.models.handoff import HandoffResult, PartialResult
from youtube_goal_agents.models.task import Task, TaskResult, TaskStatus

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


SYNTHESIS_PROMPT = """You are an expert at synthesizing information from multiple video transcripts.

USER'S GOAL: "{goal}"

Your task:
1. Review ALL transcripts below and identify which videos are RELEVANT to the user's goal
2. EXCLUDE any videos that don't match (e.g., if user asks for pork loin, exclude pulled pork/pork butt recipes)
3. SYNTHESIZE the relevant information into ONE coherent answer
4. If there are multiple approaches/recipes, summarize the COMMON elements and note key differences
5. Focus on the specific information requested (temps, times, techniques, etc.)

Format your response as:
## Relevant Videos
- List which videos were relevant and which were excluded (and why)

## Key Information
- Synthesized answer addressing the user's goal
- Use bullet points for specific data (temps, times, etc.)
- Note if different videos suggest different approaches

## Recommended Approach
- If multiple methods exist, suggest which might work best (or note that it depends on user preference)

Keep your response focused and under 800 words. Do NOT just list each video separately - SYNTHESIZE the information."""


GOAL_REASONING_PROMPT = """You are helping decide if a user's goal is satisfied.

USER'S GOAL: "{goal}"

WHAT I DID: Created {summary_count} synthesized summary from YouTube video transcripts.
{preview}

QUESTION: Is the user's goal satisfied with this summary, or do they need the content saved to a file?

Consider:
- If they wanted information, analysis, or answers → goal is SATISFIED (I provided a summary)
- If they explicitly asked to save, export, write to file, or create a document → need to WRITE TO FILE

IMPORTANT: Summaries are usually the FINAL step. Only say "not satisfied" if the user explicitly asked for file output.

Respond in this exact format:
SATISFIED: yes or no
NEXT_STEP: (only if no) write to file

Examples:
Goal: "summarize this video" → SATISFIED: yes
Goal: "save notes to research.md" → SATISFIED: no, NEXT_STEP: write to file
Goal: "find videos and summarize" → SATISFIED: yes
Goal: "get info and export to markdown" → SATISFIED: no, NEXT_STEP: write to file"""


class SummarizeAgent(BaseAgent):
    """Agent specialized for content summarization.

    Capabilities: summarization, text_analysis

    Uses summarization services directly for DAG execution,
    returning structured data that can be used for variable resolution.
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        summarizer: TranscriptSummarizer | None = None,
        client: "AzureOpenAIChatClient | None" = None,
    ) -> None:
        """Initialize with registry and optional dependencies.

        :param registry: Registry for agent discovery and task submission
        :param summarizer: Optional TranscriptSummarizer instance for dependency injection
        :param client: Optional chat client for dependency injection
        """
        super().__init__(registry, client)
        self._summarizer = summarizer or TranscriptSummarizer()

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
                    summary = await self._summarizer.summarize(
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
                summary = await self._summarizer.summarize(
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
            # Combine all transcripts for cross-video synthesis
            combined_content = []
            for t in transcripts:
                title = t.get("title", "Unknown")
                text = t.get("text", "")[:8000]  # Limit per transcript
                combined_content.append(f"=== VIDEO: {title} ===\n{text}")

            all_transcripts = "\n\n".join(combined_content)

            synthesized = await self._summarizer.summarize(
                transcript_text=all_transcripts,
                video_title="Multiple Videos",
                system_prompt=SYNTHESIS_PROMPT.format(goal=goal),
            )

            # Return as single synthesized summary
            summaries = [{
                "video_id": "synthesized",
                "title": "Synthesized Research",
                "summary": synthesized,
            }]

            output = {
                "summaries": summaries,
                "count": len(summaries),
                "goal": goal,
            }

            # Use LLM to reason about whether the goal is satisfied
            reasoning = await self._reason_about_goal(goal, output)

            if reasoning["satisfied"]:
                return HandoffResult.complete(output)
            else:
                return HandoffResult.handoff(
                    intent=reasoning["next_step"],
                    state={**state, "summarize": output},
                )

        except Exception as e:
            return PartialResult(
                error=f"Summarization failed: {e}",
                partial_data=state,
            )

    async def _reason_about_goal(
        self, goal: str, summary_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Use LLM to reason about whether the goal is satisfied.

        :param goal: Original user request
        :param summary_data: The summaries we generated
        :return: Dict with 'satisfied' (bool) and 'next_step' (str if not satisfied)
        """
        summary_count = summary_data.get("count", 0)
        preview = ""
        if summary_data.get("summaries"):
            first = summary_data["summaries"][0]
            text = first.get("summary", "")[:200]
            preview = f"Preview: {text}..."

        prompt = GOAL_REASONING_PROMPT.format(
            goal=goal,
            summary_count=summary_count,
            preview=preview,
        )

        try:
            client = self._client
            response = await client.get_response(prompt)
            text = response.text.strip()

            text_lower = text.lower()
            satisfied = "satisfied: yes" in text_lower or "satisfied:yes" in text_lower

            next_step = ""
            if not satisfied:
                # Use explicit handoff intent for writer routing
                next_step = "write to file"

            return {"satisfied": satisfied, "next_step": next_step}

        except Exception:
            # On error, default to complete (summarization is usually the final step)
            return {"satisfied": True, "next_step": ""}
