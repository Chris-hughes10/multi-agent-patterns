"""Transcript tools - LLM-callable wrappers.

This module contains tool functions for transcript operations.
Business logic is in services/youtube.py and services/storage.py.

All tool functions are async to avoid blocking the event loop.
"""

import asyncio
import logging
from typing import Annotated

from pydantic import Field

from youtube_agent_orchestrator.models.config import get_runtime_config
from youtube_agent_orchestrator.services.storage import TranscriptStorage
from youtube_agent_orchestrator.services.youtube import (
    TranscriptFetcher,
    TranscriptFetchError,
    YouTubeTranscriptFetcher,
    extract_video_id,
    fetch_transcript,
)

__all__ = [
    "TranscriptFetchError",
    "TranscriptFetcher",
    "YouTubeTranscriptFetcher",
    "extract_video_id",
    "fetch_transcript",
    "fetch_video_transcript",
    "store_video_transcript",
    "lookup_stored_transcript",
    "list_stored_transcripts",
]

logger = logging.getLogger("youtube_agent.tools.transcript")


async def fetch_video_transcript(
    video_url_or_id: Annotated[
        str, Field(description="YouTube video URL or video ID to fetch transcript for")
    ],
) -> str:
    """Fetch transcript from a YouTube video, using cached version if available.

    Checks storage first to avoid re-fetching. If not cached, fetches from
    YouTube and optionally saves to storage.

    :param video_url_or_id: YouTube URL or video ID
    :return: The full transcript text
    """
    try:
        storage = TranscriptStorage()

        # Extract video ID to check storage
        video_id = extract_video_id(video_url_or_id)

        # Check if we already have this transcript (file I/O - use thread)
        stored = await asyncio.to_thread(storage.load, video_id)
        if stored:
            logger.debug("Cache hit for video %s: %s", video_id, stored.metadata.title)
            return f"Transcript for '{stored.metadata.title}' (from cache):\n\n{stored.transcript.full_text}"

        # Not cached, fetch from YouTube
        logger.debug("Cache miss for video %s, fetching from YouTube", video_id)
        result = await fetch_transcript(video_url_or_id)

        # Save if auto-store is enabled
        config = get_runtime_config()
        if config.auto_store_transcripts:
            await asyncio.to_thread(storage.save, result)

        return f"Transcript for '{result.metadata.title}':\n\n{result.transcript.full_text}"
    except Exception as e:
        return f"Error fetching transcript: {e}"


async def store_video_transcript(
    video_url_or_id: Annotated[
        str, Field(description="YouTube video URL or video ID to fetch and store")
    ],
) -> str:
    """Fetch and store a transcript for later retrieval.

    :param video_url_or_id: YouTube URL or video ID
    :return: Confirmation message with video ID
    """
    try:
        storage = TranscriptStorage()
        result = await fetch_transcript(video_url_or_id)
        stored = await asyncio.to_thread(storage.save, result)
        return f"Stored transcript for '{stored.metadata.title}' (ID: {stored.video_id})"
    except Exception as e:
        return f"Error storing transcript: {e}"


async def lookup_stored_transcript(
    video_id: Annotated[str, Field(description="Video ID to look up in storage")],
) -> str:
    """Look up a previously stored transcript.

    :param video_id: The video ID to look up
    :return: The stored transcript or not found message
    """
    storage = TranscriptStorage()
    stored = await asyncio.to_thread(storage.load, video_id)
    if stored is None:
        return f"No stored transcript found for video ID: {video_id}"

    result = f"Stored transcript for '{stored.metadata.title}':\n"
    result += f"Video ID: {stored.video_id}\n"
    result += f"Stored at: {stored.stored_at}\n"
    if stored.summary:
        result += "Has summary: Yes\n"
    result += f"\nTranscript:\n{stored.transcript.full_text}"
    return result


async def list_stored_transcripts() -> str:
    """List all stored transcript video IDs.

    :return: List of stored video IDs or empty message
    """
    storage = TranscriptStorage()
    video_ids = await asyncio.to_thread(storage.list_videos)

    if not video_ids:
        return "No transcripts stored yet."

    result = f"Stored transcripts ({len(video_ids)} total):\n"
    for vid in video_ids:
        stored = await asyncio.to_thread(storage.load, vid)
        if stored:
            title = stored.metadata.title or "Unknown"
            result += f"  - {vid}: {title}\n"
        else:
            result += f"  - {vid}\n"

    return result
