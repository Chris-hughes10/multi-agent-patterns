"""Summarize Agent - generates summaries from transcripts."""

from typing import Annotated

from agent_framework import ChatAgent
from pydantic import Field

from youtube_agent.agents.client import get_chat_client
from youtube_agent.tools.storage import load_transcript
from youtube_agent.tools.summarize import TranscriptSummarizer, summarize_video

SUMMARIZE_AGENT_INSTRUCTIONS = """You are a Summarize Agent. Your job is to generate summaries from YouTube video transcripts.

You can:
1. Summarize a video directly by URL/ID (fetches and summarizes)
2. Summarize a stored transcript by video ID
3. Summarize arbitrary text provided to you

When summarizing:
- Capture the main topic and key points
- Highlight important insights or takeaways
- Keep summaries concise but informative
- Preserve any significant quotes or statistics

You only summarize - you do not search or fetch transcripts. Other agents handle those tasks."""


def summarize_youtube_video(
    video_url_or_id: Annotated[
        str, Field(description="YouTube video URL or video ID to summarize")
    ],
    save: Annotated[
        bool, Field(description="Whether to save the transcript and summary")
    ] = True,
) -> str:
    """Fetch, summarize, and optionally save a YouTube video.

    :param video_url_or_id: YouTube URL or video ID
    :param save: Whether to save to storage (default True)
    :return: The summary text
    """
    try:
        result = summarize_video(video_url_or_id, save=save)
        output = f"Summary of '{result.metadata.title}':\n\n{result.summary}"
        if save:
            output += f"\n\n(Saved with ID: {result.video_id})"
        return output
    except Exception as e:
        return f"Error summarizing video: {e}"


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
            summarize_youtube_video,
            summarize_stored_transcript,
            summarize_text,
        ],
    )
