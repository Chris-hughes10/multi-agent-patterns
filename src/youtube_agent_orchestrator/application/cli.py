"""CLI entry point using Click and shared driver functions."""

import asyncio
import sys

import click

from youtube_agent_orchestrator.application.main import (
    create_orchestrator,
    get_summary,
    get_transcript,
    list_stored_transcripts,
    lookup_transcript,
    process_request,
    search_videos,
    setup_logging,
)
from youtube_agent_orchestrator.application.status import setup_status_monitoring
from youtube_agent_orchestrator.models.config import get_runtime_config


@click.group(invoke_without_command=True)
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """YouTube Agent - search, fetch transcripts, summarize, and research videos.

    Uses the Orchestrator agent to coordinate specialized agents for
    YouTube video research tasks.
    """
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug

    log_file = setup_logging(debug)
    if log_file:
        click.echo(f"Debug logs: {log_file}")

    # Always enable human-friendly status updates
    setup_status_monitoring()

    # Default to chat if no command specified
    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)


@cli.command()
@click.argument("query")
@click.option("-n", "--max-results", default=5, help="Maximum results (default: 5)")
def search(query: str, max_results: int) -> None:
    """Search YouTube for videos matching QUERY."""
    result = asyncio.run(search_videos(query, max_results))
    click.echo(result)


@cli.command()
@click.argument("video")
@click.option("--save", is_flag=True, help="Save transcript to data/transcripts/")
def transcript(video: str, save: bool) -> None:
    """Fetch transcript for a YouTube VIDEO (URL or ID)."""
    try:
        result = get_transcript(video, save=save)
        click.echo(f"Title: {result.metadata.title}")
        click.echo(f"Channel: {result.metadata.channel}")
        click.echo(f"Duration: {result.transcript.duration_seconds:.0f} seconds")
        click.echo(f"\n{result.transcript.full_text}")

        if save:
            click.echo(f"\n(Saved to data/transcripts/{result.metadata.video_id}.json)")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("video")
@click.option("--no-save", is_flag=True, help="Don't save to storage")
def summarize(video: str, no_save: bool) -> None:
    """Fetch transcript and generate AI summary for VIDEO."""
    try:
        result = get_summary(video, save=not no_save)
        click.echo(f"Title: {result.metadata.title}")
        click.echo(f"Channel: {result.metadata.channel}")
        click.echo(f"\nSummary:\n{result.summary}")
        if not no_save:
            click.echo(f"\n(Saved with ID: {result.video_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list")
def list_transcripts() -> None:
    """List all stored transcripts."""
    transcripts = list_stored_transcripts()

    if not transcripts:
        click.echo("No transcripts stored yet.")
        return

    click.echo(f"Stored transcripts ({len(transcripts)} total):\n")
    for t in transcripts:
        has_summary = "yes" if t["has_summary"] else "no"
        click.echo(f"  {t['video_id']}: {t['title']} [summary: {has_summary}]")


@cli.command()
@click.argument("video_id")
def lookup(video_id: str) -> None:
    """Look up a stored transcript by VIDEO_ID."""
    stored = lookup_transcript(video_id)

    if stored is None:
        click.echo(f"No stored transcript found for: {video_id}", err=True)
        sys.exit(1)

    click.echo(f"Title: {stored.metadata.title}")
    click.echo(f"Channel: {stored.metadata.channel}")
    click.echo(f"Stored at: {stored.stored_at}")

    if stored.summary:
        click.echo(f"\nSummary:\n{stored.summary}")

    click.echo(f"\nTranscript:\n{stored.transcript.full_text}")


@cli.command()
@click.argument("request", required=False)
@click.option("--no-store", is_flag=True, help="Don't auto-save transcripts to storage")
def chat(request: str | None, no_store: bool) -> None:
    """Interactive chat with the orchestrator agent.

    If REQUEST is provided, processes it and exits.
    Otherwise, enters interactive mode.
    """
    # Configure auto-store based on --no-store flag
    if no_store:
        get_runtime_config().auto_store_transcripts = False

    orchestrator = create_orchestrator()

    async def run_interactive() -> None:
        click.echo("\nYouTube Research Agent")
        click.echo("=" * 50)
        click.echo("I can help you search, fetch transcripts, and summarize YouTube videos.")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        while True:
            try:
                user_input = click.prompt("You", default="", show_default=False)

                if not user_input.strip():
                    continue

                if user_input.strip().lower() in ("exit", "quit"):
                    click.echo("Goodbye!")
                    break

                click.echo("\nAgent: ", nl=False)
                response = await process_request(user_input, orchestrator=orchestrator)
                click.echo(response)
                click.echo()

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except click.exceptions.Abort:
                click.echo("\nGoodbye!")
                break
            except Exception as e:
                click.echo(f"\nError: {e}\n", err=True)

    async def run_single(req: str) -> None:
        response = await process_request(req, orchestrator=orchestrator)
        click.echo(response)

    if request:
        asyncio.run(run_single(request))
    else:
        asyncio.run(run_interactive())


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
