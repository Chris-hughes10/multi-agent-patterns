"""Context Provider for the YouTube Agent.

Provides dynamic context about stored transcripts to help the agent
make better decisions about when to search vs. use cached data.
"""

from typing import Any

from agent_framework import ContextProvider, SessionContext

from youtube_agent_orchestrator.services.storage import TranscriptStorage


class TranscriptContextProvider(ContextProvider):
    """Provides context about stored transcripts to the orchestrator.

    Before each agent invocation, this provider checks what transcripts
    are stored and injects that information as additional instructions.
    This helps the agent decide whether to search YouTube or use
    existing cached transcripts.
    """

    DEFAULT_SOURCE_ID = "transcript_context"

    def __init__(self, source_id: str | None = None) -> None:
        super().__init__(source_id or self.DEFAULT_SOURCE_ID)
        self._storage = TranscriptStorage()
        self._discussed_videos: set[str] = set()

    async def before_run(
        self,
        *,
        agent: Any,  # noqa: ARG002
        session: Any,  # noqa: ARG002
        context: SessionContext,
        state: dict[str, Any],  # noqa: ARG002
    ) -> None:
        """Inject instructions about available stored transcripts."""
        video_ids = self._storage.list_videos()

        if not video_ids:
            context.extend_instructions(
                self.source_id,
                "\n\n## Available Transcripts\nNo transcripts are currently stored.",
            )
            return

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

        context.extend_instructions(self.source_id, instructions)

    async def after_run(
        self,
        *,
        agent: Any,  # noqa: ARG002
        session: Any,  # noqa: ARG002
        context: SessionContext,  # noqa: ARG002
        state: dict[str, Any],  # noqa: ARG002
    ) -> None:
        """Hook for post-invocation processing.

        Currently a no-op — we rely on storage to track what's been fetched
        rather than parsing the response.
        """

    def mark_video_discussed(self, video_id: str) -> None:
        """Mark a video as having been discussed in this conversation."""
        self._discussed_videos.add(video_id)

    def reset(self) -> None:
        """Reset the conversation context."""
        self._discussed_videos.clear()
