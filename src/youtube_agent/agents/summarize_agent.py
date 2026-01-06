"""Summarize Agent - generates summaries from transcripts."""

from typing import Annotated

from agent_framework import ChatAgent
from pydantic import Field

from youtube_agent.agents.client import get_chat_client
from youtube_agent.tools.storage import load_transcript
from youtube_agent.tools.summarize import TranscriptSummarizer

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


def summarize_stored_transcript(
    video_id: Annotated[str, Field(description="Video ID of stored transcript to summarize")],
) -> str:
    """Summarize a previously stored transcript.

    :param video_id: The video ID to summarize
    :return: The summary text
    """
    stored = load_transcript(video_id)
    if stored is None:
        return f"No stored transcript found for video ID: {video_id}"

    if stored.summary:
        return f"Summary of '{stored.metadata.title}' (cached):\n\n{stored.summary}"

    try:
        summarizer = TranscriptSummarizer()
        summary = summarizer.summarize(
            transcript_text=stored.transcript.full_text,
            video_title=stored.metadata.title,
        )
        return f"Summary of '{stored.metadata.title}':\n\n{summary}"
    except Exception as e:
        return f"Error summarizing stored transcript: {e}"


def summarize_text(
    text: Annotated[str, Field(description="Text content to summarize")],
    context: Annotated[
        str | None, Field(description="Optional context about the text (e.g., video title)")
    ] = None,
) -> str:
    """Summarize arbitrary text content.

    :param text: The text to summarize
    :param context: Optional context for better summarization
    :return: The summary text
    """
    try:
        summarizer = TranscriptSummarizer()
        summary = summarizer.summarize(
            transcript_text=text,
            video_title=context,
        )
        return summary
    except Exception as e:
        return f"Error summarizing text: {e}"


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
