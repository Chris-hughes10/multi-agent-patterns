"""Main CLI entry point for the YouTube Agent system."""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from youtube_agent.agents.orchestrator import create_orchestrator
from youtube_agent.cli.status import setup_status_monitoring
from youtube_agent.models.config import get_runtime_config
from youtube_agent.services.storage import TranscriptStorage
from youtube_agent.services.youtube import fetch_transcript
from youtube_agent.tools.search import search_youtube_formatted
from youtube_agent.tools.summarize import summarize_video

logger = logging.getLogger("youtube_agent")


def setup_logging(debug: bool = False) -> str | None:
    """Configure logging for the application.

    :param debug: If True, enable DEBUG level logging
    :return: Path to log file if debug mode, None otherwise
    """
    level = logging.DEBUG if debug else logging.WARNING
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"

    # Basic console logging
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
    )

    log_file_path = None

    # Also log to file in debug mode
    if debug:
        log_dir = Path("data/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = log_dir / f"session_{timestamp}.log"

        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

        # Add file handler to root logger
        logging.getLogger().addHandler(file_handler)

        # Enable debug for httpx/openai to see API calls
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

        logger.info("Logging to file: %s", log_file_path)

    return str(log_file_path) if log_file_path else None


def cmd_search(args: argparse.Namespace) -> None:
    """Handle search command."""
    result = search_youtube_formatted(args.query, args.max_results)
    print(result)


def cmd_transcript(args: argparse.Namespace) -> None:
    """Handle transcript command."""
    try:
        result = fetch_transcript(args.video)
        print(f"Title: {result.metadata.title}")
        print(f"Channel: {result.metadata.channel}")
        print(f"Duration: {result.transcript.duration_seconds:.0f} seconds")
        print(f"\n{result.transcript.full_text}")

        if args.save:
            storage = TranscriptStorage()
            storage.save(result)
            print(f"\n(Saved to data/transcripts/{result.metadata.video_id}.json)")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_summarize(args: argparse.Namespace) -> None:
    """Handle summarize command."""
    try:
        result = summarize_video(args.video, save=not args.no_save)
        print(f"Title: {result.metadata.title}")
        print(f"Channel: {result.metadata.channel}")
        print(f"\nSummary:\n{result.summary}")
        if not args.no_save:
            print(f"\n(Saved with ID: {result.video_id})")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(_args: argparse.Namespace) -> None:
    """Handle list command."""
    storage = TranscriptStorage()
    video_ids = storage.list_videos()

    if not video_ids:
        print("No transcripts stored yet.")
        return

    print(f"Stored transcripts ({len(video_ids)} total):\n")
    for vid in video_ids:
        stored = storage.load(vid)
        if stored:
            title = stored.metadata.title or "Unknown"
            has_summary = "yes" if stored.summary else "no"
            print(f"  {vid}: {title} [summary: {has_summary}]")


def cmd_lookup(args: argparse.Namespace) -> None:
    """Handle lookup command."""
    storage = TranscriptStorage()
    stored = storage.load(args.video_id)

    if stored is None:
        print(f"No stored transcript found for: {args.video_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Title: {stored.metadata.title}")
    print(f"Channel: {stored.metadata.channel}")
    print(f"Stored at: {stored.stored_at}")

    if stored.summary:
        print(f"\nSummary:\n{stored.summary}")

    print(f"\nTranscript:\n{stored.transcript.full_text}")


def cmd_chat(args: argparse.Namespace) -> None:
    """Handle chat command."""
    orchestrator = create_orchestrator()

    async def run_interactive() -> None:
        print("YouTube Research Agent")
        print("=" * 50)
        print("I can help you search, fetch transcripts, and summarize YouTube videos.")
        print("Type 'exit' or 'quit' to stop.\n")

        while True:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit"):
                    print("Goodbye!")
                    break

                print("\nAgent: ", end="", flush=True)
                response = await orchestrator.run(user_input)
                print(response)
                print()

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}\n", file=sys.stderr)

    async def run_single(request: str) -> None:
        response = await orchestrator.run(request)
        print(response)

    if args.request:
        asyncio.run(run_single(args.request))
    else:
        asyncio.run(run_interactive())


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="youtube-agent",
        description="YouTube Agent - search, fetch transcripts, summarize, and research videos",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging to see what's happening"
    )
    parser.add_argument("--status", action="store_true", help="Show human-friendly status updates")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # search command
    search_parser = subparsers.add_parser("search", help="Search YouTube for videos")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "-n", "--max-results", type=int, default=5, help="Maximum results (default: 5)"
    )
    search_parser.set_defaults(func=cmd_search)

    # transcript command
    transcript_parser = subparsers.add_parser("transcript", help="Fetch transcript for a video")
    transcript_parser.add_argument("video", help="YouTube video URL or ID")
    transcript_parser.add_argument(
        "--save", action="store_true", help="Save transcript to data/transcripts/"
    )
    transcript_parser.set_defaults(func=cmd_transcript)

    # summarize command
    summarize_parser = subparsers.add_parser("summarize", help="Summarize a video")
    summarize_parser.add_argument("video", help="YouTube video URL or ID")
    summarize_parser.add_argument("--no-save", action="store_true", help="Don't save to storage")
    summarize_parser.set_defaults(func=cmd_summarize)

    # list command
    list_parser = subparsers.add_parser("list", help="List stored transcripts")
    list_parser.set_defaults(func=cmd_list)

    # lookup command
    lookup_parser = subparsers.add_parser("lookup", help="Look up a stored transcript")
    lookup_parser.add_argument("video_id", help="Video ID to look up")
    lookup_parser.set_defaults(func=cmd_lookup)

    # chat command
    chat_parser = subparsers.add_parser("chat", help="Interactive chat with the orchestrator agent")
    chat_parser.add_argument(
        "request", nargs="?", help="Single request (interactive if not provided)"
    )
    chat_parser.add_argument(
        "--no-store", action="store_true", help="Don't auto-save transcripts to storage"
    )
    chat_parser.set_defaults(func=cmd_chat)

    args = parser.parse_args()
    log_file = setup_logging(args.debug)
    if log_file:
        print(f"Debug logs: {log_file}")

    # Always enable human-friendly status updates
    setup_status_monitoring()

    # Configure auto-store based on --no-store flag (for chat command)
    no_store = getattr(args, "no_store", False)
    if no_store:
        get_runtime_config().auto_store_transcripts = False

    if args.command is None:
        # Default to chat if no command specified
        args.request = None
        args.no_store = False  # Default value for interactive mode
        cmd_chat(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
