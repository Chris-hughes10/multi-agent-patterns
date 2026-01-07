"""PlannerAgent - Creates execution DAGs from user requests.

The Planner analyzes user requests and available agents to create
a structured execution plan (DAG) that can be executed with parallel
and sequential steps.
"""

import json
import logging
from typing import TYPE_CHECKING

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent.infra.client import get_chat_client
from youtube_agent_v2.patterns.dag_executor import DAGStep, ExecutionDAG

if TYPE_CHECKING:
    from youtube_agent_v2.core.registry import AgentRegistry

logger = logging.getLogger("youtube_agent_v2.planner")


def _build_agent_catalog(registry: "AgentRegistry") -> str:
    """Build a catalog of available agents for the planner prompt.

    :param registry: Agent registry
    :return: Formatted string describing available agents
    """
    lines = []
    for agent in registry.all_agents():
        description = getattr(agent, "description", None)
        if description is None:
            description = f"Handles: {', '.join(agent.capabilities)}"
        lines.append(f"- **{agent.name}**: {description}")
        lines.append(f"  Capabilities: {', '.join(agent.capabilities)}")
    return "\n".join(lines)


PLANNER_SYSTEM_PROMPT = """You are a Planning Agent. Your job is to analyze user requests and create execution plans.

Given a user's goal and a list of available agents, you create a DAG (Directed Acyclic Graph) of steps
that will accomplish the goal. Each step is executed by a specific agent.

## Available Agents

{agent_catalog}

## Planning Rules

1. **Identify the goal**: What does the user ultimately want?
2. **Break down into steps**: What individual tasks are needed?
3. **Assign agents**: Which agent is best suited for each task?
4. **Define dependencies**: Which steps must complete before others can start?
5. **Enable parallelism**: Steps without dependencies can run in parallel

## Variable References

Steps can reference outputs from previous steps using `$step_id` syntax:
- `$search` - entire output of the "search" step
- `$search.results` - the "results" field from search output
- `$search.results[0]` - first item in results array
- `$search.results[0].video_id` - video_id from first result

## Output Format

Respond with a JSON object containing the execution plan:

```json
{{
  "goal": "Brief summary of the user's goal",
  "steps": [
    {{
      "id": "search",
      "agent": "search",
      "description": "Search for videos about X",
      "input": {{"query": "search terms"}},
      "depends_on": []
    }},
    {{
      "id": "transcript_1",
      "agent": "transcript",
      "description": "Get transcript for first video",
      "input": {{"video_id": "$search.results[0].video_id"}},
      "depends_on": ["search"]
    }},
    {{
      "id": "summarize",
      "agent": "summarize",
      "description": "Summarize the transcript",
      "input": {{"text": "$transcript_1", "focus": ["key points"]}},
      "depends_on": ["transcript_1"]
    }}
  ]
}}
```

## Important Notes

- Use descriptive step IDs (not just numbers)
- Include clear descriptions for each step
- Maximize parallelism by minimizing unnecessary dependencies
- Only include steps that are actually needed
- Reference previous step outputs using $ syntax
"""


REPLAN_SYSTEM_PROMPT = """You are a Planning Agent performing error recovery.

A previous execution plan failed at a specific step. You need to create a revised plan
that works around the failure, using the partial results that were collected.

## Available Agents

{agent_catalog}

## Previous Results

The following steps completed successfully:
{completed_results}

## Failure Information

Failed step: {failed_step}
Error: {error}

## Your Task

Create a new plan that:
1. Reuses the successful results (don't repeat those steps)
2. Works around the failure (try alternative approaches)
3. Still achieves the original goal if possible

If the goal cannot be achieved, create a plan that delivers partial value.

Respond with a JSON execution plan in the same format as before.
"""


class PlannerAgent:
    """Agent that creates execution DAGs from user requests.

    The Planner uses an LLM to analyze user requests and available agents,
    then produces a structured execution plan (DAG) that can be run by
    the DAGExecutor.

    :param registry: Agent registry for discovering available agents
    :param client: Optional chat client for LLM calls
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,
    ) -> None:
        """Initialize the planner.

        :param registry: Registry of available agents
        :param client: Optional chat client
        """
        self._registry = registry
        self._client = client or get_chat_client()
        self._chat_agent: ChatAgent | None = None

    @property
    def name(self) -> str:
        """Return agent name."""
        return "planner"

    def _get_chat_agent(self) -> ChatAgent:
        """Get or create the ChatAgent for planning."""
        if self._chat_agent is None:
            agent_catalog = _build_agent_catalog(self._registry)
            instructions = PLANNER_SYSTEM_PROMPT.format(agent_catalog=agent_catalog)

            self._chat_agent = ChatAgent(
                chat_client=self._client,
                name=self.name,
                instructions=instructions,
                tools=[],
            )
        return self._chat_agent

    async def create_plan(self, user_request: str) -> ExecutionDAG:
        """Create an execution plan for a user request.

        :param user_request: The user's natural language request
        :return: ExecutionDAG ready for execution
        :raises ValueError: If LLM response cannot be parsed
        """
        chat_agent = self._get_chat_agent()

        prompt = f"""Create an execution plan for this request:

"{user_request}"

Respond ONLY with a valid JSON object containing the plan. No other text."""

        response = await chat_agent.run(prompt)
        return self._parse_dag_response(response.text, user_request)

    async def replan(
        self,
        original_goal: str,
        completed_results: dict[str, any],
        failed_step: str,
        error: str,
    ) -> ExecutionDAG:
        """Create a revised plan after a failure.

        :param original_goal: The original user goal
        :param completed_results: Results from steps that succeeded
        :param failed_step: ID of the step that failed
        :param error: Error message from the failure
        :return: Revised ExecutionDAG
        """
        agent_catalog = _build_agent_catalog(self._registry)

        # Format completed results
        results_str = "\n".join(
            f"- {step_id}: {json.dumps(result, default=str)[:200]}..."
            for step_id, result in completed_results.items()
        )
        if not results_str:
            results_str = "(no steps completed)"

        instructions = REPLAN_SYSTEM_PROMPT.format(
            agent_catalog=agent_catalog,
            completed_results=results_str,
            failed_step=failed_step,
            error=error,
        )

        # Create a fresh agent for re-planning
        replan_agent = ChatAgent(
            chat_client=self._client,
            name=f"{self.name}_replan",
            instructions=instructions,
            tools=[],
        )

        prompt = f"""The original goal was:

"{original_goal}"

Create a revised plan that works around the failure and still achieves the goal.
Respond ONLY with a valid JSON object containing the plan."""

        response = await replan_agent.run(prompt)
        return self._parse_dag_response(response.text, original_goal)

    def _parse_dag_response(self, response_text: str, goal: str) -> ExecutionDAG:
        """Parse the LLM response into an ExecutionDAG.

        :param response_text: Raw LLM response
        :param goal: The original goal (fallback if not in response)
        :return: ExecutionDAG
        :raises ValueError: If response cannot be parsed
        """
        # Try to extract JSON from the response
        text = response_text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse planner response: {e}")
            logger.debug(f"Response text: {text}")
            raise ValueError(f"Failed to parse planner response as JSON: {e}")

        # Validate required fields
        if "steps" not in data:
            raise ValueError("Planner response missing 'steps' field")

        # Use provided goal or extract from response
        dag_goal = data.get("goal", goal)

        # Create DAG from parsed data
        dag = ExecutionDAG.from_dict({"goal": dag_goal, "steps": data["steps"]})

        # Validate the DAG
        errors = dag.validate()
        if errors:
            raise ValueError(f"Invalid DAG structure: {'; '.join(errors)}")

        return dag

    def create_simple_plan(
        self,
        steps: list[dict[str, any]],
        goal: str = "",
    ) -> ExecutionDAG:
        """Create a plan programmatically (without LLM).

        Useful for testing or when the plan is known in advance.

        :param steps: List of step definitions
        :param goal: The goal for this plan
        :return: ExecutionDAG
        """
        dag_steps = []
        for step_data in steps:
            dag_steps.append(
                DAGStep(
                    id=step_data["id"],
                    agent_name=step_data.get("agent", step_data.get("agent_name", "")),
                    description=step_data.get("description", ""),
                    input_template=step_data.get("input", {}),
                    depends_on=step_data.get("depends_on", []),
                )
            )
        return ExecutionDAG(goal=goal, steps=dag_steps)
