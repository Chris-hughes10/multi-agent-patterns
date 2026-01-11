"""CLI entry point using shared driver functions."""

import asyncio
import logging

import click

from youtube_autonomous_agents.cli.main import (
    create_synthesizer,
    list_agents,
    process_request,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube_autonomous_agents.cli")


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
    request = f"Search YouTube for: {query}. Return up to {max_results} results."
    result = asyncio.run(process_request(request))
    click.echo(result)


@cli.command()
@click.argument("video_id")
def transcript(video_id: str) -> None:
    """Fetch transcript for VIDEO_ID."""
    request = f"Fetch the transcript for YouTube video: {video_id}"
    result = asyncio.run(process_request(request))
    click.echo(result)


@cli.command()
@click.argument("video_id")
def summarize(video_id: str) -> None:
    """Summarize stored transcript for VIDEO_ID."""
    request = f"Summarize the stored transcript for video: {video_id}"
    result = asyncio.run(process_request(request))
    click.echo(result)


@cli.command()
@click.argument("content")
@click.argument("filename")
@click.option("-d", "--output-dir", default="output", help="Output directory")
def write(content: str, filename: str, output_dir: str) -> None:
    """Write CONTENT to FILENAME as markdown."""
    request = f"Write the following content to {filename} in {output_dir}: {content}"
    result = asyncio.run(process_request(request))
    click.echo(result)


@cli.command()
def agents() -> None:
    """List registered agents and their capabilities."""
    agent_list = list_agents()

    click.echo("\nRegistered Agents:")
    click.echo("-" * 40)

    for agent in agent_list:
        click.echo(f"\n  {agent['name']}:")
        click.echo(f"    Capabilities: {', '.join(agent['capabilities'])}")

    click.echo("\n" + "-" * 40)
    click.echo(f"Total: {len(agent_list)} agents")

    all_caps = set()
    for agent in agent_list:
        all_caps.update(agent["capabilities"])
    click.echo(f"All capabilities: {', '.join(sorted(all_caps))}")


@cli.command()
@click.option("-r", "--request", "user_request", default=None, help="Single request (interactive if not provided)")
@click.option("-t", "--max-transcripts", default=5, help="Maximum transcripts to fetch (default: 5)")
def chat(user_request: str | None, max_transcripts: int) -> None:
    """Interactive chat mode with the SynthesizerAgent."""
    context = {"max_transcripts": max_transcripts}

    async def run_chat() -> None:
        synth = create_synthesizer()

        click.echo("\nYouTube Autonomous Agents - Interactive Mode")
        click.echo("=" * 50)
        click.echo("Powered by SynthesizerAgent with autonomous coordination.")
        click.echo(f"Max transcripts: {max_transcripts}")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        # Single request mode
        if user_request:
            click.echo("[Synthesizer] Processing request...")
            result = await process_request(user_request, context=context, synthesizer=synth)
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
                result = await process_request(user_input, context=context, synthesizer=synth)
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
