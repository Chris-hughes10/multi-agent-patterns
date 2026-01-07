"""Shared Azure OpenAI chat client for agents."""

from functools import lru_cache

from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential

from youtube_agent.models.config import get_settings


@lru_cache
def get_chat_client() -> AzureOpenAIChatClient:
    """Get a cached Azure OpenAI chat client.

    Uses Azure CLI credentials with the configured tenant ID.
    The client is cached to avoid recreating connections.

    :return: Configured AzureOpenAIChatClient
    :raises ValueError: If Azure OpenAI is not configured
    """
    settings = get_settings()

    if not settings.is_configured:
        raise ValueError(
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT "
            "and AZURE_OPENAI_DEPLOYMENT environment variables."
        )

    # Use Azure CLI credential with tenant ID if configured
    credential_kwargs = {}
    if settings.azure_tenant_id:
        credential_kwargs["tenant_id"] = settings.azure_tenant_id

    credential = AzureCliCredential(**credential_kwargs)

    return AzureOpenAIChatClient(
        credential=credential,
        endpoint=settings.azure_openai_endpoint,
        deployment_name=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
    )
