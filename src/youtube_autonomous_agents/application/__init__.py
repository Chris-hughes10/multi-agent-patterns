"""V2 application layer - CLI and driver functions."""

from youtube_autonomous_agents.application.cli import cli, main
from youtube_autonomous_agents.application.main import (
    create_registry,
    create_synthesizer,
    list_agents,
    process_request,
)

__all__ = [
    "cli",
    "main",
    "create_registry",
    "create_synthesizer",
    "list_agents",
    "process_request",
]
