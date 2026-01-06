"""Context Provider for the YouTube Agent.

Provides dynamic context about stored transcripts to help the agent
make better decisions about when to search vs. use cached data.
"""

from collections.abc import MutableSequence, Sequence
from typing import Any

from agent_framework._memory import Context, ContextProvider
from agent_framework._types import ChatMessage

from youtube_agent.tools.storage import TranscriptStorage


class TranscriptContextProvider(ContextProvider):
    """Provides context about stored transcripts to the orchestrator.

    Before each agent invocation, this provider checks what transcripts
    are stored and injects that information as additional context.
    This helps the agent decide whether to search YouTube or use
    existing cached transcripts.
    """

    def __init__(self) -> None:
        """Initialize the context provider."""
        self._storage = TranscriptStorage()
        self._discussed_videos: set[str] = set()

    async def invoking(
        self,
        messages: ChatMessage | MutableSequence[ChatMessage],  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Context:
        """Called before the agent invokes the LLM.

        Provides context about available stored transcripts.

        :param messages: The messages being sent to the agent
        :return: Additional context to inject
        """
        # Get list of stored transcripts
        video_ids = self._storage.list_videos()

        if not video_ids:
            return Context(
                instructions="\n\n## Available Transcripts\nNo transcripts are currently stored."
            )

        # Build a summary of stored transcripts
        transcript_info = []
        for vid in video_ids:
            stored = self._storage.load(vid)
            if stored:
                title = stored.metadata.title or "Unknown"
                channel = stored.metadata.channel or "Unknown"
                has_summary = "yes" if stored.summary else "no"
                transcript_info.append(
                    f'  - {vid}: "{title}" by {channel} [summary: {has_summary}]'
                )

        stored_list = "\n".join(transcript_info)

        # Track which videos we've discussed recently
        recently_discussed = ""
        if self._discussed_videos:
            recently_discussed = (
                f"\n\nVideos discussed in this conversation: {', '.join(self._discussed_videos)}"
            )

        instructions = f"""

## Available Transcripts ({len(video_ids)} stored)
The following transcripts are already cached and available for immediate use:
{stored_list}
{recently_discussed}

IMPORTANT: If the user asks about content from these videos or channels, use the TranscriptAgent
to look them up instead of searching YouTube again. Only search if you need new videos."""

        return Context(instructions=instructions)

    async def invoked(
        self,
        request_messages: ChatMessage | Sequence[ChatMessage],
        response_messages: ChatMessage | Sequence[ChatMessage] | None = None,
        invoke_exception: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Called after the agent receives a response.

        Tracks which videos were discussed in this conversation.

        :param request_messages: Messages sent to the agent
        :param response_messages: Messages received from the agent
        :param invoke_exception: Any exception that occurred
        """
        # Could parse response_messages to track discussed video IDs
        # For now, we rely on the storage to track what's been fetched
        pass

    def mark_video_discussed(self, video_id: str) -> None:
        """Mark a video as having been discussed in this conversation.

        :param video_id: The video ID that was discussed
        """
        self._discussed_videos.add(video_id)

    def reset(self) -> None:
        """Reset the conversation context."""
        self._discussed_videos.clear()
