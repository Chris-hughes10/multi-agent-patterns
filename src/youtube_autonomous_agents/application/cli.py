"""CLI entry point using SynthesizerAgent for autonomous multi-agent coordination."""

import asyncio
import logging

import click

from youtube_autonomous_agents.agents import (
    SearchAgent,
    SummarizeAgent,
    SynthesizerAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_autonomous_agents.infra import AgentRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube_autonomous_agents.application")


def create_registry() -> AgentRegistry:
    """Create and populate an agent registry with all agents.

    :return: Configured AgentRegistry
    """
    registry = AgentRegistry()

    # Create and register all agents
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


def create_synthesizer() -> SynthesizerAgent:
    """Create the SynthesizerAgent - the user-facing entry point.

    :return: Configured SynthesizerAgent
    """
    registry = create_registry()
    return SynthesizerAgent(registry)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """YouTube Autonomous Agents - Multi-agent task processing.

    Uses the SynthesizerAgent as the entry point for all requests.
    The Synthesizer analyzes requests, coordinates agents via the
    self-selecting pool, and synthesizes final responses.
    """
    if verbose:
        logging.getLogger("youtube_autonomous_agents").setLevel(logging.DEBUG)


@cli.command()
@click.argument("query")
@click.option("-n", "--max-results", default=5, help="Maximum results to return")
def search(query: str, max_results: int) -> None:
    """Search YouTube for videos matching QUERY."""

    async def run() -> None:
        synth = create_synthesizer()
        request = f"Search YouTube for: {query}. Return up to {max_results} results."
        result = await synth.process_request(request)
        click.echo(result)

    asyncio.run(run())


@cli.command()
@click.argument("video_id")
def transcript(video_id: str) -> None:
    """Fetch transcript for VIDEO_ID."""

    async def run() -> None:
        synth = create_synthesizer()
        request = f"Fetch the transcript for YouTube video: {video_id}"
        result = await synth.process_request(request)
        click.echo(result)

    asyncio.run(run())


@cli.command()
@click.argument("video_id")
def summarize(video_id: str) -> None:
    """Summarize stored transcript for VIDEO_ID."""

    async def run() -> None:
        synth = create_synthesizer()
        request = f"Summarize the stored transcript for video: {video_id}"
        result = await synth.process_request(request)
        click.echo(result)

    asyncio.run(run())


@cli.command()
@click.argument("content")
@click.argument("filename")
@click.option("-d", "--output-dir", default="output", help="Output directory")
def write(content: str, filename: str, output_dir: str) -> None:
    """Write CONTENT to FILENAME as markdown."""

    async def run() -> None:
        synth = create_synthesizer()
        request = f"Write the following content to {filename} in {output_dir}: {content}"
        result = await synth.process_request(request)
        click.echo(result)

    asyncio.run(run())


@cli.command()
def agents() -> None:
    """List registered agents and their capabilities."""
    registry = create_registry()

    click.echo("\nRegistered Agents:")
    click.echo("-" * 40)

    for agent in registry.all_agents():
        click.echo(f"\n  {agent.name}:")
        click.echo(f"    Capabilities: {', '.join(agent.capabilities)}")

    click.echo("\n" + "-" * 40)
    click.echo(f"Total: {len(registry)} agents")
    click.echo(f"All capabilities: {', '.join(registry.all_capabilities())}")


@cli.command()
@click.option("-r", "--request", default=None, help="Single request (interactive if not provided)")
def chat(request: str | None) -> None:
    """Interactive chat mode with the SynthesizerAgent."""

    async def run_chat() -> None:
        synth = create_synthesizer()

        click.echo("\nYouTube Autonomous Agents - Interactive Mode")
        click.echo("=" * 50)
        click.echo("Powered by SynthesizerAgent with autonomous coordination.")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        # Single request mode
        if request:
            click.echo("[Synthesizer] Processing request...")
            result = await synth.process_request(request)
            click.echo(result)
            return

        # Interactive loop
        while True:
            try:
                user_input = click.prompt("You", default="", show_default=False)

                if not user_input.strip():
                    continue

                if user_input.strip().lower() in ("exit", "quit"):
                    click.echo("Goodbye!")
                    break

                click.echo("\n[Synthesizer] Processing...")
                result = await synth.process_request(user_input)
                click.echo(f"\nAgent: {result}\n")

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except click.exceptions.Abort:
                click.echo("\nGoodbye!")
                break

    asyncio.run(run_chat())


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
