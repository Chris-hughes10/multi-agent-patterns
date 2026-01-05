"""Main CLI entry point for the YouTube Agent system."""

import argparse
import asyncio
import sys

from youtube_agent.agents.orchestrator import create_orchestrator
from youtube_agent.tools.search import search_youtube_formatted
from youtube_agent.tools.storage import TranscriptStorage
from youtube_agent.tools.summarize import summarize_video
from youtube_agent.tools.transcript import fetch_transcript


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


def cmd_list(args: argparse.Namespace) -> None:
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
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # search command
    search_parser = subparsers.add_parser("search", help="Search YouTube for videos")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "-n", "--max-results", type=int, default=5, help="Maximum results (default: 5)"
    )
    search_parser.set_defaults(func=cmd_search)

    # transcript command
    transcript_parser = subparsers.add_parser(
        "transcript", help="Fetch transcript for a video"
    )
    transcript_parser.add_argument("video", help="YouTube video URL or ID")
    transcript_parser.set_defaults(func=cmd_transcript)

    # summarize command
    summarize_parser = subparsers.add_parser("summarize", help="Summarize a video")
    summarize_parser.add_argument("video", help="YouTube video URL or ID")
    summarize_parser.add_argument(
        "--no-save", action="store_true", help="Don't save to storage"
    )
    summarize_parser.set_defaults(func=cmd_summarize)

    # list command
    list_parser = subparsers.add_parser("list", help="List stored transcripts")
    list_parser.set_defaults(func=cmd_list)

    # lookup command
    lookup_parser = subparsers.add_parser("lookup", help="Look up a stored transcript")
    lookup_parser.add_argument("video_id", help="Video ID to look up")
    lookup_parser.set_defaults(func=cmd_lookup)

    # chat command
    chat_parser = subparsers.add_parser(
        "chat", help="Interactive chat with the orchestrator agent"
    )
    chat_parser.add_argument(
        "request", nargs="?", help="Single request (interactive if not provided)"
    )
    chat_parser.set_defaults(func=cmd_chat)

    args = parser.parse_args()

    if args.command is None:
        # Default to chat if no command specified
        args.request = None
        cmd_chat(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
