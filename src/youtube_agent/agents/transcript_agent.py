"""Transcript Agent - manages YouTube video transcripts."""

from typing import Annotated

from agent_framework import ChatAgent
from pydantic import Field

from youtube_agent.agents.client import get_chat_client
from youtube_agent.tools.storage import TranscriptStorage, load_transcript, save_transcript
from youtube_agent.tools.transcript import fetch_transcript

TRANSCRIPT_AGENT_INSTRUCTIONS = """You are a Transcript Agent. Your job is to manage YouTube video transcripts.

You can:
1. Fetch transcripts from YouTube videos (using video URLs or IDs)
2. Store transcripts for later use
3. Look up previously stored transcripts
4. List all stored transcripts

When fetching:
- Accept YouTube URLs or video IDs
- Return the full transcript text
- Report any errors (video not found, no transcript available, etc.)

You only manage transcripts - you do not summarize them. The Summarize Agent handles that."""


# Agent-friendly tool wrappers with proper annotations


def fetch_video_transcript(
    video_url_or_id: Annotated[
        str, Field(description="YouTube video URL or video ID to fetch transcript for")
    ],
) -> str:
    """Fetch transcript from a YouTube video.

    :param video_url_or_id: YouTube URL or video ID
    :return: The full transcript text
    """
    try:
        result = fetch_transcript(video_url_or_id)
        return f"Transcript for '{result.metadata.title}':\n\n{result.transcript.full_text}"
    except Exception as e:
        return f"Error fetching transcript: {e}"


def store_video_transcript(
    video_url_or_id: Annotated[
        str, Field(description="YouTube video URL or video ID to fetch and store")
    ],
) -> str:
    """Fetch and store a transcript for later retrieval.

    :param video_url_or_id: YouTube URL or video ID
    :return: Confirmation message with video ID
    """
    try:
        result = fetch_transcript(video_url_or_id)
        stored = save_transcript(result)
        return f"Stored transcript for '{stored.metadata.title}' (ID: {stored.video_id})"
    except Exception as e:
        return f"Error storing transcript: {e}"


def lookup_stored_transcript(
    video_id: Annotated[str, Field(description="Video ID to look up in storage")],
) -> str:
    """Look up a previously stored transcript.

    :param video_id: The video ID to look up
    :return: The stored transcript or not found message
    """
    stored = load_transcript(video_id)
    if stored is None:
        return f"No stored transcript found for video ID: {video_id}"

    result = f"Stored transcript for '{stored.metadata.title}':\n"
    result += f"Video ID: {stored.video_id}\n"
    result += f"Stored at: {stored.stored_at}\n"
    if stored.summary:
        result += "Has summary: Yes\n"
    result += f"\nTranscript:\n{stored.transcript.full_text}"
    return result


def list_stored_transcripts() -> str:
    """List all stored transcript video IDs.

    :return: List of stored video IDs or empty message
    """
    storage = TranscriptStorage()
    video_ids = storage.list_videos()

    if not video_ids:
        return "No transcripts stored yet."

    result = f"Stored transcripts ({len(video_ids)} total):\n"
    for vid in video_ids:
        stored = storage.load(vid)
        if stored:
            title = stored.metadata.title or "Unknown"
            result += f"  - {vid}: {title}\n"
        else:
            result += f"  - {vid}\n"

    return result


def create_transcript_agent() -> ChatAgent:
    """Create a Transcript Agent instance.

    :return: Configured ChatAgent for transcript management
    """
    client = get_chat_client()

    return ChatAgent(
        chat_client=client,
        name="TranscriptAgent",
        instructions=TRANSCRIPT_AGENT_INSTRUCTIONS,
        tools=[
            fetch_video_transcript,
            store_video_transcript,
            lookup_stored_transcript,
            list_stored_transcripts,
        ],
    )
