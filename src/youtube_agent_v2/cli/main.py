"""V2 CLI entry point with multi-agent patterns."""

import asyncio
import contextlib
import logging
import sys
from enum import Enum

import click

from youtube_agent_v2.agents import (
    SearchAgent,
    SummarizeAgent,
    SynthesizerAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_agent_v2.core import AgentRegistry, TaskResult
from youtube_agent_v2.core.models.handoff import HandoffResult, PartialResult
from youtube_agent_v2.patterns.dispatcher import DispatcherCoordinator
from youtube_agent_v2.patterns.self_selection import SelfSelectingPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube_agent_v2.cli")


class Pattern(str, Enum):
    """Available multi-agent patterns."""

    DISPATCHER = "dispatcher"
    SELF_SELECTION = "self-selection"
    PLANNER = "planner"
    AUTONOMOUS = "autonomous"


# Global pattern setting (set by CLI group)
_current_pattern: Pattern = Pattern.DISPATCHER


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


async def run_with_dispatcher(
    registry: AgentRegistry,
    description: str,
    capabilities: list[str],
    context: dict | None = None,
) -> TaskResult:
    """Run a task using the dispatcher pattern.

    :param registry: Agent registry
    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional context dict
    :return: TaskResult
    """
    dispatcher = DispatcherCoordinator(registry)
    dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=3))

    try:
        result = await dispatcher.submit_and_wait(
            description=description,
            capabilities=capabilities,
            context=context or {},
            timeout=120.0,
        )
        return result

    finally:
        await dispatcher.shutdown(wait=True)
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task


async def run_with_self_selection(
    registry: AgentRegistry,
    description: str,
    capabilities: list[str],
    context: dict | None = None,
) -> TaskResult:
    """Run a task using the self-selection pattern.

    :param registry: Agent registry
    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional context dict
    :return: TaskResult
    """
    pool = SelfSelectingPool(registry)
    await pool.start()

    try:
        result = await pool.submit_and_wait(
            description=description,
            capabilities=capabilities,
            context=context or {},
            timeout=120.0,
        )
        return result

    finally:
        await pool.shutdown(wait=True)


async def run_with_planner(
    registry: AgentRegistry,
    description: str,
) -> TaskResult:
    """Run a task using the planner + DAG pattern.

    The Planner creates an execution DAG, then the DAGExecutor
    runs it with parallel execution and dependency tracking.

    :param registry: Agent registry
    :param description: Natural language task description
    :return: TaskResult
    """
    from youtube_agent_v2.agents.planner import PlannerAgent

    click.echo("[Planning...] Creating execution plan", nl=False)

    # Preview the plan first
    planner = PlannerAgent(registry=registry)
    try:
        dag = await planner.create_plan(description)
        click.echo(f" ✓ ({len(dag.steps)} steps)")

        # Show the plan
        click.echo(f"[Plan] Goal: {dag.goal}")
        for step in dag.steps:
            deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
            click.echo(f"  → {step.id}: {step.description}{deps}")

        click.echo("[Executing...] Running DAG")

    except ValueError as e:
        click.echo(f" ✗ Failed: {e}")
        return TaskResult(success=False, error=str(e))

    # Execute through synthesizer
    synthesizer = SynthesizerAgent(registry=registry)

    result = await synthesizer.process_request(
        user_request=description,
        pattern="planner",
    )

    if isinstance(result, PartialResult):
        return TaskResult(
            success=False,
            error=result.error or "Planner execution failed",
            data=result.partial_data,
        )
    elif isinstance(result, HandoffResult):
        return TaskResult(
            success=True,
            data=result.result,
        )
    else:
        # String response from synthesizer
        return TaskResult(
            success=True,
            data=result,
        )


async def run_with_autonomous(
    registry: AgentRegistry,
    description: str,
) -> TaskResult:
    """Run a task using the autonomous pattern.

    Agents receive the goal and accumulated state, reason about what
    to do next, and hand off to each other until the goal is satisfied.

    :param registry: Agent registry
    :param description: Natural language task description
    :return: TaskResult
    """
    click.echo("[Autonomous] Starting agent chain...")

    synthesizer = SynthesizerAgent(registry=registry)

    result = await synthesizer.process_request(
        user_request=description,
        pattern="autonomous",
    )

    # Show execution path
    path_summary = synthesizer.session.get_path_summary()
    if path_summary:
        click.echo(f"[Path] {path_summary}")

    if isinstance(result, PartialResult):
        return TaskResult(
            success=False,
            error=result.error or "Autonomous execution failed",
            data=result.partial_data,
        )
    elif isinstance(result, HandoffResult):
        return TaskResult(success=True, data=result.result)
    else:
        # String response from synthesizer
        return TaskResult(success=True, data=result)


async def run_task(
    description: str,
    capabilities: list[str],
    context: dict | None = None,
) -> None:
    """Run a task using the currently selected pattern.

    :param description: Task description
    :param capabilities: Required capabilities
    :param context: Optional context dict
    """
    registry = create_registry()

    logger.info("Using pattern: %s", _current_pattern.value)
    logger.info("Submitting task: %s", description)
    logger.info("Required capabilities: %s", capabilities)

    if _current_pattern == Pattern.DISPATCHER:
        result = await run_with_dispatcher(registry, description, capabilities, context)
    elif _current_pattern == Pattern.SELF_SELECTION:
        result = await run_with_self_selection(registry, description, capabilities, context)
    elif _current_pattern == Pattern.PLANNER:
        result = await run_with_planner(registry, description)
    else:  # Pattern.AUTONOMOUS
        result = await run_with_autonomous(registry, description)

    if result.success:
        click.echo("\n" + "=" * 60)
        click.echo(f"RESULT (via {_current_pattern.value}):")
        click.echo("=" * 60)
        click.echo(result.data)
    else:
        click.echo(f"\nTask failed: {result.error}", err=True)
        sys.exit(1)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option(
    "-p",
    "--pattern",
    type=click.Choice(["dispatcher", "self-selection", "planner", "autonomous"]),
    default="dispatcher",
    help="Multi-agent pattern to use (default: dispatcher)",
)
def cli(verbose: bool, pattern: str) -> None:
    """YouTube Agent V2 - Multi-agent task processing.

    Supports four coordination patterns:
    - dispatcher: Central coordinator assigns tasks to agents
    - self-selection: Agents autonomously claim tasks from queue
    - planner: LLM creates execution DAG, then parallel execution
    - autonomous: Agents reason about goals and hand off to each other
    """
    global _current_pattern  # noqa: PLW0603

    if verbose:
        logging.getLogger("youtube_agent_v2").setLevel(logging.DEBUG)

    _current_pattern = Pattern(pattern)


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


@cli.command()
def patterns() -> None:
    """Show available multi-agent patterns."""
    click.echo("\nAvailable Patterns:")
    click.echo("-" * 40)

    click.echo("\n  dispatcher (default):")
    click.echo("    Central coordinator pulls tasks from queue")
    click.echo("    and assigns them to capable agents.")
    click.echo("    Good for: Controlled execution, simple selection logic")

    click.echo("\n  self-selection:")
    click.echo("    Agents autonomously watch queue and compete")
    click.echo("    to claim tasks they can handle.")
    click.echo("    Good for: Scalability, natural load balancing")

    click.echo("\n  planner:")
    click.echo("    An LLM Planner creates an execution DAG upfront,")
    click.echo("    then DAGExecutor runs steps with dependency tracking.")
    click.echo("    Supports parallel execution and re-planning on failure.")
    click.echo("    Good for: Complex multi-step workflows, inspectable plans")

    click.echo("\n  autonomous:")
    click.echo("    Agents receive the goal and accumulated state,")
    click.echo("    reason about what to do next, and hand off to each other")
    click.echo("    until the goal is satisfied. No central planning.")
    click.echo("    Good for: Adaptive execution, emergent workflows")

    click.echo("\n" + "-" * 40)
    click.echo("Usage: youtube-agent-v2 -p <pattern> <command>")


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
        click.echo(f"Pattern: {_current_pattern.value}")
        click.echo("Commands: search, transcript, summarize, write")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        # Set up the coordinator based on pattern
        if _current_pattern == Pattern.DISPATCHER:
            dispatcher = DispatcherCoordinator(registry)
            dispatch_task = asyncio.create_task(dispatcher.run(max_concurrent=3))

            async def submit(desc: str, caps: list[str]) -> TaskResult:
                return await dispatcher.submit_and_wait(
                    description=desc,
                    capabilities=caps,
                    context={},
                    timeout=120.0,
                )

            async def cleanup() -> None:
                await dispatcher.shutdown(wait=True)
                dispatch_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dispatch_task

        elif _current_pattern == Pattern.SELF_SELECTION:
            pool = SelfSelectingPool(registry)
            await pool.start()

            async def submit(desc: str, caps: list[str]) -> TaskResult:
                return await pool.submit_and_wait(
                    description=desc,
                    capabilities=caps,
                    context={},
                    timeout=120.0,
                )

            async def cleanup() -> None:
                await pool.shutdown(wait=True)

        elif _current_pattern == Pattern.PLANNER:
            synthesizer = SynthesizerAgent(registry=registry)

            async def submit(desc: str, _caps: list[str]) -> TaskResult:
                click.echo("[Planning...] Creating execution plan", nl=False)

                # Create planner and get the plan
                from youtube_agent_v2.agents.planner import PlannerAgent

                planner = PlannerAgent(registry=registry)
                try:
                    dag = await planner.create_plan(desc)
                    click.echo(f" ✓ ({len(dag.steps)} steps)")

                    # Show the plan
                    click.echo(f"[Plan] Goal: {dag.goal}")
                    for step in dag.steps:
                        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
                        click.echo(f"  → {step.id}: {step.description}{deps}")

                    click.echo("[Executing...] Running DAG")

                except ValueError as e:
                    click.echo(f" ✗ Failed: {e}")
                    return TaskResult(success=False, error=str(e))

                # Now run through synthesizer for full execution
                result = await synthesizer.process_request(
                    user_request=desc,
                    pattern="planner",
                )
                if isinstance(result, PartialResult):
                    return TaskResult(success=False, error=result.error, data=result.partial_data)
                elif isinstance(result, HandoffResult):
                    return TaskResult(success=True, data=result.result)
                else:
                    return TaskResult(success=True, data=result)

            async def cleanup() -> None:
                pass  # Synthesizer doesn't need cleanup

        else:  # Pattern.AUTONOMOUS
            synthesizer = SynthesizerAgent(registry=registry)

            async def submit(desc: str, _caps: list[str]) -> TaskResult:
                click.echo("[Autonomous] Starting agent chain...")

                result = await synthesizer.process_request(
                    user_request=desc,
                    pattern="autonomous",
                )

                # Show execution path
                path_summary = synthesizer.session.get_path_summary()
                if path_summary:
                    click.echo(f"[Path] {path_summary}")

                if isinstance(result, PartialResult):
                    return TaskResult(
                        success=False,
                        error=result.error,
                        data=result.partial_data,
                    )
                elif isinstance(result, HandoffResult):
                    return TaskResult(success=True, data=result.result)
                else:
                    return TaskResult(success=True, data=result)

            async def cleanup() -> None:
                pass  # Synthesizer doesn't need cleanup

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
            await cleanup()

    asyncio.run(run_chat())


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
