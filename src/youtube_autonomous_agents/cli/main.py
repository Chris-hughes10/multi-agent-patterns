"""Driver module - shared logic for CLI and programmatic usage.

This module provides the core driver functions that can be used by:
- CLI commands
- E2E tests
- Programmatic API consumers
"""

import logging

from youtube_autonomous_agents.agents import (
    SearchAgent,
    SummarizeAgent,
    SynthesizerAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_autonomous_agents.infra import AgentRegistry

logger = logging.getLogger("youtube_autonomous_agents.driver")


def create_registry() -> AgentRegistry:
    """Create and populate an agent registry with all agents.

    :return: Configured AgentRegistry with all V2 agents registered
    """
    registry = AgentRegistry()

    # Register all agents
    registry.register(SearchAgent(registry))
    registry.register(TranscriptAgent(registry))
    registry.register(SummarizeAgent(registry))
    registry.register(WriterAgent(registry))

    logger.info(
        "Registered %d agents: %s",
        len(registry),
        [a.name for a in registry.all_agents()],
    )

    return registry


def create_synthesizer(registry: AgentRegistry | None = None) -> SynthesizerAgent:
    """Create a SynthesizerAgent - the user-facing entry point.

    :param registry: Optional pre-configured registry (creates new if None)
    :return: Configured SynthesizerAgent
    """
    if registry is None:
        registry = create_registry()
    return SynthesizerAgent(registry)


async def process_request(
    request: str,
    timeout: float = 120.0,
    context: dict | None = None,
    synthesizer: SynthesizerAgent | None = None,
) -> str:
    """Process a user request through the autonomous agent system.

    This is the main driver function that handles:
    - Creating the synthesizer (if not provided)
    - Processing the request
    - Returning the synthesized response

    :param request: Natural language user request
    :param timeout: Request timeout in seconds
    :param context: Optional context dict with config (e.g., max_transcripts)
    :param synthesizer: Optional pre-created synthesizer (creates new if None)
    :return: Synthesized response string
    """
    if synthesizer is None:
        synthesizer = create_synthesizer()

    return await synthesizer.process_request(request, timeout=timeout, context=context)


def list_agents() -> list[dict]:
    """List all registered agents and their capabilities.

    :return: List of dicts with agent name and capabilities
    """
    registry = create_registry()
    return [
        {"name": agent.name, "capabilities": list(agent.capabilities)}
        for agent in registry.all_agents()
    ]
