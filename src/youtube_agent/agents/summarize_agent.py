"""Summarize Agent - generates summaries from transcripts."""

from agent_framework import ChatAgent

from youtube_agent.infra.client import get_chat_client
from youtube_agent.tools.summarize import summarize_stored_transcript, summarize_text

SUMMARIZE_AGENT_INSTRUCTIONS = """You are a Summarize Agent. Your job is to generate summaries from text content.

You can:
1. Summarize a stored transcript by video ID
2. Summarize arbitrary text provided to you

When summarizing:
- Capture the main topic and key points
- Highlight important insights or takeaways
- Keep summaries concise but informative
- Preserve any significant quotes or statistics

IMPORTANT: You do NOT fetch transcripts yourself. The TranscriptAgent handles fetching.
If given transcript text directly, summarize it. If given a video ID, use summarize_stored_transcript."""


def create_summarize_agent() -> ChatAgent:
    """Create a Summarize Agent instance.

    :return: Configured ChatAgent for summarization
    """
    client = get_chat_client()

    return ChatAgent(
        chat_client=client,
        name="SummarizeAgent",
        instructions=SUMMARIZE_AGENT_INSTRUCTIONS,
        tools=[
            summarize_stored_transcript,
            summarize_text,
        ],
    )
