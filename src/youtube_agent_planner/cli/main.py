"""CLI entry point for youtube-agent-planner.

Provides DAG-based execution planning with explicit plan visibility.
"""

import asyncio
import logging

import click

from youtube_agent_planner.main import create_planner, create_registry
from youtube_agent_planner.patterns.dag_executor import DAGExecutor
from youtube_autonomous_agents.infra import AgentRegistry
from youtube_autonomous_agents.infra.session import Session
from youtube_autonomous_agents.models.handoff import PartialResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube_agent_planner.cli")


async def run_with_planning(
    request: str,
    registry: AgentRegistry,
) -> str | None:
    """Run a request using the planner + DAG pattern with CLI output.

    This is a CLI-specific wrapper that adds user-facing output.
    For programmatic use, use youtube_agent_planner.main.process_request().

    :param request: User's natural language request
    :param registry: Agent registry with registered agents
    :return: Result string or None on failure
    """
    planner = create_planner(registry)
    session = Session()

    # Create plan
    click.echo("[Planning...] Creating execution plan", nl=False)
    try:
        dag = await planner.create_plan(request)
        click.echo(f" ✓ ({len(dag.steps)} steps)")
    except ValueError as e:
        click.echo(" ✗ Failed")
        click.echo(f"Planning error: {e}", err=True)
        return None

    # Display the plan
    click.echo(f"[Plan] Goal: {dag.goal}")
    for step in dag.steps:
        deps_str = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        click.echo(f"  → {step.id}: {step.description}{deps_str}")

    # Execute the DAG
    click.echo("[Executing...] Running DAG")
    executor = DAGExecutor(
        registry=registry,
        session=session,
        planner=planner,  # Enable re-planning on failure
    )

    result = await executor.execute(dag)

    if isinstance(result, PartialResult):
        click.echo(f"\nPartial result (error: {result.error}):", err=True)
        if result.partial_data:
            return str(result.partial_data)
        return None
    else:
        # Get the last step's result (usually the final output)
        if result:
            last_step_id = dag.steps[-1].id
            final_result = result.get(last_step_id, result)
            if isinstance(final_result, dict) and "summary" in final_result:
                return final_result["summary"]
            elif isinstance(final_result, str):
                return final_result
            else:
                return str(final_result)
        return None


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """YouTube Agent Planner - DAG-based execution planning.

    Uses LLM to create an explicit execution plan (DAG), then runs
    the steps with dependency tracking and parallel execution.

    For autonomous agent chains without upfront planning, use:
      uv run youtube-agent-v2
    """
    if verbose:
        logging.getLogger("youtube_agent_planner").setLevel(logging.DEBUG)
        logging.getLogger("youtube_autonomous_agents").setLevel(logging.DEBUG)


@cli.command()
@click.option("-r", "--request", default=None, help="Single request (interactive if not provided)")
def chat(request: str | None) -> None:
    """Interactive chat mode with planner + DAG execution."""

    async def run_chat() -> None:
        registry = create_registry()

        click.echo("\nYouTube Agent Planner - Interactive Mode")
        click.echo("=" * 50)
        click.echo("Creates explicit execution plans before running.")
        click.echo("Type 'exit' or 'quit' to stop.\n")

        # Single request mode
        if request:
            result = await run_with_planning(request, registry)
            if result:
                click.echo("\n" + result)
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

                click.echo("\nAgent: ", nl=False)
                result = await run_with_planning(user_input, registry)
                if result:
                    click.echo("\n" + result)
                click.echo()

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except click.exceptions.Abort:
                click.echo("\nGoodbye!")
                break

    asyncio.run(run_chat())


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


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
