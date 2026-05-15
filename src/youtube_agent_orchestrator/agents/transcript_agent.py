"""Transcript Agent - manages YouTube video transcripts."""

from agent_framework import Agent

from youtube_agent_orchestrator.infra.client import get_chat_client, get_default_options
from youtube_agent_orchestrator.tools.youtube import (
    fetch_video_transcript,
    list_stored_transcripts,
    lookup_stored_transcript,
    store_video_transcript,
)

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


def create_transcript_agent() -> Agent:
    """Create a Transcript Agent instance.

    :return: Configured Agent for transcript management
    """
    return Agent(
        client=get_chat_client(),
        name="TranscriptAgent",
        instructions=TRANSCRIPT_AGENT_INSTRUCTIONS,
        tools=[
            fetch_video_transcript,
            store_video_transcript,
            lookup_stored_transcript,
            list_stored_transcripts,
        ],
        default_options=get_default_options(),
    )
