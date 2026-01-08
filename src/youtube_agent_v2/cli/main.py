"""V2 CLI entry point with unified autonomous + self-selection pattern."""

import asyncio
import logging
import sys

import click

from youtube_agent_v2.agents import (
    SearchAgent,
    SummarizeAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_agent_v2.core import AgentRegistry, TaskResult
from youtube_agent_v2.patterns.self_selection import SelfSelectingPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube_agent_v2.cli")


def create_registry() -> AgentRegistry:
    """Create and populate an agent registry with all V2 agents.

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


async def run_task(
    description: str,
    capabilities: list[str],
    context: dict | None = None,
) -> None:
    """Run a task using the unified autonomous + self-selection pattern.

    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional context dict
    """
    registry = create_registry()

    logger.info("Submitting task: %s", description)
    logger.info("Required capabilities: %s", capabilities)

    click.echo("[Autonomous] Starting agent chain...")

    # Use the unified pattern: event-driven self-selection with autonomous handoffs
    pool = SelfSelectingPool(registry)
    await pool.start()

    try:
        result = await pool.submit_and_wait(
            description=description,
            capabilities=capabilities,
            context=context or {},
            timeout=120.0,
        )

        if result.success:
            click.echo("\n" + "=" * 60)
            click.echo("RESULT:")
            click.echo("=" * 60)
            click.echo(result.data)
        else:
            click.echo(f"\nTask failed: {result.error}", err=True)
            sys.exit(1)

    finally:
        await pool.shutdown(wait=True)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """YouTube Agent V2 - Autonomous multi-agent task processing.

    Uses event-driven self-selection with autonomous handoffs.
    Agents reason about goals and hand off to each other via
    a shared queue until the task is complete.
    """
    if verbose:
        logging.getLogger("youtube_agent_v2").setLevel(logging.DEBUG)


@cli.command()
@click.argument("query")
@click.option("-n", "--max-results", default=5, help="Maximum results to return")
def search(query: str, max_results: int) -> None:
    """Search YouTube for videos matching QUERY."""
    asyncio.run(
        run_task(
            description=f"Search YouTube for: {query}. Return up to {max_results} results.",
            capabilities=["youtube_search"],
        )
    )


@cli.command()
@click.argument("video_id")
def transcript(video_id: str) -> None:
    """Fetch transcript for VIDEO_ID."""
    asyncio.run(
        run_task(
            description=f"Fetch the transcript for YouTube video: {video_id}",
            capabilities=["transcript_fetch"],
            context={"video_id": video_id},
        )
    )


@cli.command()
@click.argument("video_id")
def summarize(video_id: str) -> None:
    """Summarize stored transcript for VIDEO_ID."""
    asyncio.run(
        run_task(
            description=f"Summarize the stored transcript for video: {video_id}",
            capabilities=["summarization"],
            context={"video_id": video_id},
        )
    )


@cli.command()
@click.argument("content")
@click.argument("filename")
@click.option("-d", "--output-dir", default="output", help="Output directory")
def write(content: str, filename: str, output_dir: str) -> None:
    """Write CONTENT to FILENAME as markdown."""
    asyncio.run(
        run_task(
            description=f"Write the following content to {filename} in {output_dir}: {content}",
            capabilities=["file_export"],
        )
    )


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


def _infer_capabilities(user_input: str) -> list[str]:
    """Infer required capabilities from user input.

    :param user_input: Natural language user request
    :return: List of capability strings
    """
    text = user_input.lower()

    # Keywords that map to single-agent capabilities
    capability_keywords = {
        "youtube_search": ["search", "find", "look for", "discover", "videos about"],
        "transcript_fetch": ["transcript", "captions", "subtitles", "fetch text"],
        "summarization": ["summarize", "summary", "tldr", "overview", "key points"],
        "file_export": ["write", "save", "export", "create file", "markdown"],
    }

    matched = []
    for capability, keywords in capability_keywords.items():
        if any(kw in text for kw in keywords):
            matched.append(capability)

    # Default to search if no specific capability matched
    return matched if matched else ["youtube_search"]


@cli.command()
@click.option("-r", "--request", default=None, help="Single request (interactive if not provided)")
def chat(request: str | None) -> None:
    """Interactive chat mode with multi-agent system."""

    async def run_chat() -> None:
        registry = create_registry()

        click.echo("\nYouTube Agent V2 - Interactive Mode")
        click.echo("=" * 50)
        click.echo("Autonomous agents with event-driven self-selection.")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        # Use the unified pattern: event-driven self-selection with autonomous handoffs
        pool = SelfSelectingPool(registry)
        await pool.start()

        async def submit(desc: str, caps: list[str]) -> TaskResult:
            click.echo("[Autonomous] Starting agent chain...")
            return await pool.submit_and_wait(
                description=desc,
                capabilities=caps,
                context={"goal": desc},
                timeout=120.0,
            )

        try:
            # Single request mode
            if request:
                capabilities = _infer_capabilities(request)
                logger.info("Inferred capabilities: %s", capabilities)
                result = await submit(request, capabilities)
                if result.success:
                    click.echo(result.data)
                else:
                    click.echo(f"Error: {result.error}", err=True)
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

                    capabilities = _infer_capabilities(user_input)
                    logger.info("Inferred capabilities: %s", capabilities)

                    click.echo("\nAgent: ", nl=False)
                    result = await submit(user_input, capabilities)

                    if result.success:
                        click.echo(result.data)
                    else:
                        click.echo(f"Error: {result.error}", err=True)

                    click.echo()

                except KeyboardInterrupt:
                    click.echo("\nGoodbye!")
                    break
                except click.exceptions.Abort:
                    click.echo("\nGoodbye!")
                    break

        finally:
            await pool.shutdown(wait=True)

    asyncio.run(run_chat())


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
