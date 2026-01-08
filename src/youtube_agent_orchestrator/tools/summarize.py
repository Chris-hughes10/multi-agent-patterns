"""Summarization tools - LLM-callable wrappers.

This module contains tool functions for summarization operations.
Business logic is in services/summarizer.py.

All tool functions are async to avoid blocking the event loop.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field

from youtube_agent_orchestrator.models.storage import StoredTranscript
from youtube_agent_orchestrator.models.transcript import TranscriptResult
from youtube_agent_orchestrator.services.storage import TranscriptStorage
from youtube_agent_orchestrator.services.summarizer import SummarizationError, TranscriptSummarizer

__all__ = [
    "SummarizationError",
    "TranscriptSummarizer",
    "summarize_stored_transcript",
    "summarize_text",
    "summarize_transcript",
    "summarize_video",
]


async def summarize_stored_transcript(
    video_id: Annotated[str, Field(description="Video ID of stored transcript to summarize")],
) -> str:
    """Summarize a previously stored transcript.

    :param video_id: The video ID to summarize
    :return: The summary text
    """
    storage = TranscriptStorage()
    stored = await asyncio.to_thread(storage.load, video_id)
    if stored is None:
        return f"No stored transcript found for video ID: {video_id}"

    if stored.summary:
        return f"Summary of '{stored.metadata.title}' (cached):\n\n{stored.summary}"

    try:
        summarizer = TranscriptSummarizer()
        summary = await summarizer.summarize(
            transcript_text=stored.transcript.full_text,
            video_title=stored.metadata.title,
        )
        return f"Summary of '{stored.metadata.title}':\n\n{summary}"
    except Exception as e:
        return f"Error summarizing stored transcript: {e}"


async def summarize_text(
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
        summary = await summarizer.summarize(
            transcript_text=text,
            video_title=context,
        )
        return summary
    except Exception as e:
        return f"Error summarizing text: {e}"


async def summarize_transcript(
    result: TranscriptResult,
    save: bool = True,
    storage: TranscriptStorage | None = None,
    summarizer: TranscriptSummarizer | None = None,
) -> StoredTranscript:
    """Summarize a transcript and optionally save it - main entry point.

    This fetches a summary from the LLM and stores both the transcript
    and summary together.

    :param result: The transcript result to summarize
    :param save: Whether to save the result to storage (default True)
    :param storage: Optional custom storage instance
    :param summarizer: Optional custom summarizer instance
    :return: StoredTranscript with the summary
    :raises SummarizationError: If summarization fails
    """
    summarizer = summarizer or TranscriptSummarizer()
    storage = storage or TranscriptStorage()

    summary = await summarizer.summarize_result(result)

    if save:
        return await asyncio.to_thread(storage.save, result, summary)

    # Return without persisting
    now = datetime.now(UTC)
    return StoredTranscript(
        video_id=result.metadata.video_id,
        transcript=result.transcript,
        metadata=result.metadata,
        summary=summary,
        stored_at=now,
        updated_at=now,
    )


async def summarize_video(
    url_or_id: str,
    save: bool = True,
    languages: list[str] | None = None,
) -> StoredTranscript:
    """Fetch and summarize a YouTube video - convenience function.

    Combines transcript fetching and summarization into one call.

    :param url_or_id: YouTube URL or video ID
    :param save: Whether to save the result to storage (default True)
    :param languages: Preferred transcript languages
    :return: StoredTranscript with transcript and summary
    :raises TranscriptFetchError: If transcript cannot be fetched
    :raises SummarizationError: If summarization fails
    """
    from youtube_agent_orchestrator.services.youtube import fetch_transcript

    result = await fetch_transcript(url_or_id, languages=languages)
    return await summarize_transcript(result, save=save)
