"""Shared Azure OpenAI chat client for agents."""

from functools import lru_cache

from agent_framework import ChatOptions
from agent_framework.openai import OpenAIChatClient
from azure.identity import AzureCliCredential

from youtube_agent_orchestrator.models.config import get_settings


@lru_cache
def get_chat_client() -> OpenAIChatClient:
    """Get a cached Azure OpenAI chat client.

    Uses Azure CLI credentials with the configured tenant ID.
    The client is cached to avoid recreating connections.

    :return: Configured OpenAIChatClient in Azure mode
    :raises ValueError: If Azure OpenAI is not configured
    """
    settings = get_settings()

    if not settings.is_configured:
        raise ValueError(
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT "
            "and AZURE_OPENAI_DEPLOYMENT environment variables."
        )

    credential_kwargs = {}
    if settings.azure_tenant_id:
        credential_kwargs["tenant_id"] = settings.azure_tenant_id

    credential = AzureCliCredential(**credential_kwargs)

    return OpenAIChatClient(
        model=settings.azure_openai_deployment,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        credential=credential,
    )


def get_default_options() -> ChatOptions:
    """Build default ChatOptions from settings.

    Temperature and seed moved from client construction to per-request options
    in agent-framework 1.x. Pass the result as ``default_options`` when
    constructing an Agent so every run uses these values.
    """
    settings = get_settings()
    return ChatOptions(
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
    )
