"""Driver module - shared logic for CLI and programmatic usage.

This module provides the core driver functions that can be used by:
- CLI commands
- E2E tests
- Programmatic API consumers
"""

import logging

from youtube_agent_planner.agents.planner import PlannerAgent
from youtube_agent_planner.patterns.dag_executor import DAGExecutor
from youtube_autonomous_agents.agents import (
    SearchAgent,
    SummarizeAgent,
    TranscriptAgent,
    WriterAgent,
)
from youtube_autonomous_agents.infra import AgentRegistry
from youtube_autonomous_agents.infra.session import Session
from youtube_autonomous_agents.models.handoff import PartialResult

logger = logging.getLogger("youtube_agent_planner.driver")


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


def create_planner(registry: AgentRegistry | None = None) -> PlannerAgent:
    """Create a PlannerAgent.

    :param registry: Optional pre-configured registry (creates new if None)
    :return: Configured PlannerAgent
    """
    if registry is None:
        registry = create_registry()
    return PlannerAgent(registry=registry)


async def process_request(
    request: str,
    registry: AgentRegistry | None = None,
    planner: PlannerAgent | None = None,
) -> str | None:
    """Process a user request through the planner + DAG pattern.

    This is the main driver function that handles:
    - Creating the planner (if not provided)
    - Planning the execution DAG
    - Executing the DAG
    - Returning the result

    :param request: Natural language user request
    :param registry: Optional pre-configured registry (creates new if None)
    :param planner: Optional pre-created planner (creates new if None)
    :return: Result string or None on failure
    """
    if registry is None:
        registry = create_registry()
    if planner is None:
        planner = PlannerAgent(registry=registry)

    session = Session()

    # Create plan
    logger.info("Creating execution plan for request: %s", request[:50])
    try:
        dag = await planner.create_plan(request)
        logger.info("Created plan with %d steps", len(dag.steps))
    except ValueError as e:
        logger.error("Planning failed: %s", e)
        return None

    # Execute the DAG
    logger.info("Executing DAG")
    executor = DAGExecutor(
        registry=registry,
        session=session,
        planner=planner,  # Enable re-planning on failure
    )

    result = await executor.execute(dag)

    if isinstance(result, PartialResult):
        logger.warning("Partial result (error: %s)", result.error)
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


def list_agents() -> list[dict]:
    """List all registered agents and their capabilities.

    :return: List of dicts with agent name and capabilities
    """
    registry = create_registry()
    return [
        {"name": agent.name, "capabilities": list(agent.capabilities)}
        for agent in registry.all_agents()
    ]


__all__ = [
    "create_registry",
    "create_planner",
    "process_request",
    "list_agents",
]
