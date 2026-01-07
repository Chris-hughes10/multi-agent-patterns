"""Summarization domain service - AI-powered content summarization.

This module handles transcript summarization using Azure OpenAI.
All methods are async to avoid blocking the event loop.
"""

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

from youtube_agent.models.config import Settings, get_settings
from youtube_agent.models.transcript import TranscriptResult


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
    All methods are async to avoid blocking the event loop.

    :param settings: Optional settings instance (uses defaults if not provided)
    :param client: Optional AsyncAzureOpenAI client for dependency injection
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
        client: AsyncAzureOpenAI | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or self._create_client()

    def _create_client(self) -> AsyncAzureOpenAI:
        """Create an async Azure OpenAI client from settings.

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
            return AsyncAzureOpenAI(
                api_version=self._settings.azure_openai_api_version,
                azure_endpoint=self._settings.azure_openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        # Fall back to API key authentication
        return AsyncAzureOpenAI(
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
            azure_endpoint=self._settings.azure_openai_endpoint,
        )

    async def summarize(
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
            response = await self._client.chat.completions.create(
                model=self._settings.azure_openai_deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise SummarizationError(str(e)) from e

    async def summarize_result(
        self,
        result: TranscriptResult,
        system_prompt: str | None = None,
    ) -> str:
        """Summarize a TranscriptResult.

        :param result: The transcript result to summarize
        :param system_prompt: Optional custom system prompt
        :return: The generated summary
        """
        return await self.summarize(
            transcript_text=result.transcript.full_text,
            video_title=result.metadata.title,
            system_prompt=system_prompt,
        )
