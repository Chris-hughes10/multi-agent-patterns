"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Settings can be provided via:
    - Environment variables (e.g., AZURE_OPENAI_ENDPOINT)
    - .env file in the project root

    For Azure Foundry deployments, configure:
    - AZURE_OPENAI_ENDPOINT: Your Azure Foundry endpoint URL
    - AZURE_OPENAI_DEPLOYMENT: Your model deployment name (e.g., 'gpt-52')
    - AZURE_OPENAI_API_VERSION: API version (default: 2024-12-01-preview)

    Authentication (choose one):
    - Azure AD (recommended): Run 'az login' - no additional config needed
    - API Key: Set AZURE_OPENAI_API_KEY (if key auth is enabled on your resource)

    :param azure_openai_endpoint: Azure OpenAI/Foundry endpoint URL
    :param azure_openai_api_key: Azure OpenAI API key (optional, uses Azure AD if not set)
    :param azure_openai_deployment: Deployment name for the model
    :param azure_openai_api_version: API version for Azure OpenAI
    :param default_language: Default language for transcripts
    :param max_transcript_length: Maximum transcript length before chunking
    :param storage_dir: Directory for storing transcripts and summaries
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Azure OpenAI / Azure Foundry settings
    azure_openai_endpoint: str | None = Field(
        default=None,
        description="Azure OpenAI or Azure Foundry endpoint URL",
    )
    azure_openai_api_key: str | None = Field(
        default=None,
        description="Azure OpenAI API key",
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        description="Model deployment name (e.g., 'gpt-52')",
    )
    azure_openai_api_version: str = Field(
        default="2024-12-01-preview",
        description="Azure OpenAI API version",
    )
    azure_tenant_id: str | None = Field(
        default=None,
        description="Azure AD tenant ID for authentication",
    )

    # Transcript settings
    default_language: str = Field(default="en", description="Default transcript language")
    max_transcript_length: int = Field(
        default=100000,
        description="Max characters before chunking",
    )

    # Storage settings
    storage_dir: Path = Field(
        default=Path("data/transcripts"),
        description="Directory for storing transcripts and summaries",
    )

    # Proxy settings (for YouTube transcript API)
    proxy_url: str | None = Field(
        default=None,
        description="SOCKS5 or HTTP proxy URL (e.g., socks5://user:pass@host:port)",
    )

    @property
    def is_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured.

        Requires endpoint and deployment. API key is optional
        (uses Azure AD authentication if not provided).
        """
        return bool(self.azure_openai_endpoint and self.azure_openai_deployment)

    @property
    def use_azure_ad(self) -> bool:
        """Check if Azure AD authentication should be used."""
        return not self.azure_openai_api_key


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.

    :return: Settings instance loaded from environment
    """
    return Settings()
