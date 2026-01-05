"""Tool for summarizing YouTube transcripts using Azure OpenAI."""

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AzureOpenAI

from youtube_agent.models.config import Settings, get_settings
from youtube_agent.models.transcript import TranscriptResult
from youtube_agent.tools.storage import StoredTranscript, TranscriptStorage


class SummarizationError(Exception):
    """Raised when summarization fails.

    :param reason: Human-readable reason for the failure
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Summarization failed: {reason}")


class TranscriptSummarizer:
    """Summarizes YouTube transcripts using Azure OpenAI.

    Uses the configured Azure Foundry deployment to generate summaries.

    :param settings: Optional settings instance (uses defaults if not provided)
    :param client: Optional AzureOpenAI client for dependency injection
    """

    DEFAULT_SYSTEM_PROMPT = """You are an expert at summarizing video content.
Given a YouTube video transcript, provide a clear and comprehensive summary that:
1. Captures the main topic and key points
2. Highlights important insights or takeaways
3. Is well-structured and easy to read
4. Preserves any significant quotes or statistics mentioned

Keep the summary concise but informative."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: AzureOpenAI | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or self._create_client()

    def _create_client(self) -> AzureOpenAI:
        """Create an Azure OpenAI client from settings.

        Uses Azure AD authentication by default (via DefaultAzureCredential).
        Falls back to API key if AZURE_OPENAI_API_KEY is set.
        """
        if not self._settings.is_configured:
            raise SummarizationError(
                "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_DEPLOYMENT environment variables."
            )

        if self._settings.use_azure_ad:
            # Use Azure CLI authentication to respect current az login session
            credential_kwargs = {}
            if self._settings.azure_tenant_id:
                credential_kwargs["tenant_id"] = self._settings.azure_tenant_id
            credential = AzureCliCredential(**credential_kwargs)
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            return AzureOpenAI(
                api_version=self._settings.azure_openai_api_version,
                azure_endpoint=self._settings.azure_openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        # Fall back to API key authentication
        return AzureOpenAI(
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
            azure_endpoint=self._settings.azure_openai_endpoint,
        )

    def summarize(
        self,
        transcript_text: str,
        video_title: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Summarize a transcript.

        :param transcript_text: The full transcript text to summarize
        :param video_title: Optional video title for context
        :param system_prompt: Optional custom system prompt
        :return: The generated summary
        :raises SummarizationError: If summarization fails
        """
        system = system_prompt or self.DEFAULT_SYSTEM_PROMPT

        user_content = ""
        if video_title:
            user_content = f"Video Title: {video_title}\n\n"
        user_content += f"Transcript:\n{transcript_text}"

        try:
            response = self._client.chat.completions.create(
                model=self._settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise SummarizationError(str(e)) from e

    def summarize_result(
        self,
        result: TranscriptResult,
        system_prompt: str | None = None,
    ) -> str:
        """Summarize a TranscriptResult.

        :param result: The transcript result to summarize
        :param system_prompt: Optional custom system prompt
        :return: The generated summary
        """
        return self.summarize(
            transcript_text=result.transcript.full_text,
            video_title=result.metadata.title,
            system_prompt=system_prompt,
        )


def summarize_transcript(
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

    summary = summarizer.summarize_result(result)

    if save:
        return storage.save(result, summary=summary)

    # Return without persisting
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return StoredTranscript(
        video_id=result.metadata.video_id,
        transcript=result.transcript,
        metadata=result.metadata,
        summary=summary,
        stored_at=now,
        updated_at=now,
    )


def summarize_video(
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
    from youtube_agent.tools.transcript import fetch_transcript

    result = fetch_transcript(url_or_id, languages=languages)
    return summarize_transcript(result, save=save)
