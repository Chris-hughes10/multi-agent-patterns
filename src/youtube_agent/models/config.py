"""Configuration management using pydantic-settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Settings can be provided via:
    - Environment variables (e.g., OPENAI_API_KEY)
    - .env file in the project root

    :param openai_api_key: OpenAI API key for embeddings and chat
    :param openai_model: Model to use for chat completions
    :param openai_embedding_model: Model to use for embeddings
    :param default_language: Default language for transcripts
    :param max_transcript_length: Maximum transcript length before chunking
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # OpenAI settings
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="Chat model to use")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model to use",
    )

    # Azure OpenAI settings (optional alternative to OpenAI)
    azure_openai_api_key: str | None = Field(default=None)
    azure_openai_endpoint: str | None = Field(default=None)
    azure_openai_deployment: str | None = Field(default=None)

    # Transcript settings
    default_language: str = Field(default="en", description="Default transcript language")
    max_transcript_length: int = Field(
        default=100000,
        description="Max characters before chunking",
    )

    @property
    def use_azure(self) -> bool:
        """Check if Azure OpenAI should be used instead of OpenAI."""
        return bool(
            self.azure_openai_api_key
            and self.azure_openai_endpoint
            and self.azure_openai_deployment
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.

    :return: Settings instance loaded from environment
    """
    return Settings()
