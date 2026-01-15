"""CLI layer - commands and driver functions."""

from youtube_goal_agents.cli.commands import cli, main
from youtube_goal_agents.cli.main import (
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
