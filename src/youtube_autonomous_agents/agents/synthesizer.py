"""SynthesizerAgent - User-facing entry point for multi-agent coordination.

The Synthesizer is the single point of contact for users. It:
- Receives all user messages
- Analyzes requests for parallelism opportunities
- Delegates to SelfSelectingPool for agent coordination
- Aggregates results and produces the final user-facing response

The Synthesizer is a thin wrapper that uses the pool's coordination methods,
just like any agent would for fan-out operations.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from youtube_agent_orchestrator.infra.client import get_chat_client
from youtube_autonomous_agents.infra.pool import SelfSelectingPool
from youtube_autonomous_agents.models.handoff import HandoffResult, PartialResult

if TYPE_CHECKING:
    from youtube_autonomous_agents.infra.registry import AgentRegistry


@dataclass
class RequestAnalysis:
    """Result of analyzing a user request for parallelism.

    :param has_parallelism: Whether the request contains parallel tasks
    :param parallel_intents: List of parallel task descriptions (if parallel)
    :param join_intent: What to do after parallel tasks (if parallel)
    :param first_intent: The first/only task to do (if sequential)
    """

    has_parallelism: bool
    parallel_intents: list[str] = field(default_factory=list)
    join_intent: str | None = None
    first_intent: str | None = None

    @classmethod
    def sequential(cls, intent: str) -> "RequestAnalysis":
        """Create analysis for a sequential (non-parallel) request."""
        return cls(has_parallelism=False, first_intent=intent)

    @classmethod
    def parallel(cls, intents: list[str], join_intent: str) -> "RequestAnalysis":
        """Create analysis for a parallel request."""
        return cls(
            has_parallelism=True,
            parallel_intents=intents,
            join_intent=join_intent,
        )


SYNTHESIZER_INSTRUCTIONS = """You are a Synthesizer Agent - the user's primary assistant for YouTube video research.

Your role is to:
1. Understand what the user wants to accomplish
2. Present results in a clear, helpful format
3. Summarize and synthesize information from multiple sources

You do NOT directly search, fetch transcripts, or summarize - other specialized agents do that work.
You receive their results and present them to the user in a coherent way.

When presenting results:
- Be concise but comprehensive
- Highlight key findings
- Reference sources (video titles, IDs) when relevant
- Suggest follow-up actions the user might want to take

If something went wrong during processing, explain what happened and suggest alternatives."""


class SynthesizerAgent:
    """User-facing agent that coordinates multi-agent workflows.

    The Synthesizer is a thin entry point that:
    1. Analyzes requests for parallelism (LLM-based)
    2. Delegates to SelfSelectingPool for all coordination
    3. Formats the final response

    Uses the same pool methods that agents use for fan-out operations,
    ensuring consistent behavior throughout the system.

    Supports two modes:
    - CLI mode (default): Creates and destroys pool per request
    - Service mode: Uses an external shared pool for efficiency

    :param registry: Agent registry for finding capable agents
    :param client: Optional chat client for response synthesis
    :param timeout: Default timeout for requests in seconds
    :param pool: Optional external pool for service mode (reused across requests)
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        client: AzureOpenAIChatClient | None = None,
        timeout: float = 120.0,
        pool: SelfSelectingPool | None = None,
    ) -> None:
        """Initialize the synthesizer.

        :param registry: Registry of available agents
        :param client: Optional chat client
        :param timeout: Default request timeout
        :param pool: Optional external pool (if provided, won't be shutdown after requests)
        """
        self._registry = registry
        self._client = client or get_chat_client()
        self._timeout = timeout
        self._chat_agent: ChatAgent | None = None
        self._external_pool = pool  # None = create per request (CLI mode)

    @property
    def name(self) -> str:
        """Return agent name."""
        return "synthesizer"

    def _get_chat_agent(self) -> ChatAgent:
        """Get or create the ChatAgent for response synthesis."""
        if self._chat_agent is None:
            self._chat_agent = ChatAgent(
                chat_client=self._client,
                name=self.name,
                instructions=SYNTHESIZER_INSTRUCTIONS,
                tools=[],
            )
        return self._chat_agent

    async def _get_pool(self) -> tuple[SelfSelectingPool, bool]:
        """Get or create the pool for request processing.

        Returns a tuple of (pool, should_shutdown):
        - External pool: Returns the shared pool, should_shutdown=False
        - CLI mode: Creates a new pool, should_shutdown=True

        :return: Tuple of (pool instance, whether to shutdown after use)
        """
        if self._external_pool is not None:
            # Service mode: use external pool, don't shutdown
            if not self._external_pool.is_running:
                await self._external_pool.start()
            return self._external_pool, False

        # CLI mode: create per-request pool
        pool = SelfSelectingPool(self._registry)
        await pool.start()
        return pool, True

    async def process_request(
        self,
        user_request: str,
        timeout: float | None = None,
        context: dict | None = None,
    ) -> str:
        """Process a user request through the multi-agent system.

        Analyzes the request for parallelism, delegates to pool for
        coordination, and formats the final response.

        :param user_request: The user's natural language request
        :param timeout: Optional override for request timeout
        :param context: Optional context dict with config (e.g., max_transcripts)
        :return: Synthesized response for the user
        """
        request_timeout = timeout or self._timeout
        base_context = context or {}

        # Analyze request for parallelism
        analysis = await self._analyze_request(user_request)

        # Get pool (creates new one in CLI mode, reuses in service mode)
        pool, should_shutdown = await self._get_pool()

        try:
            if analysis.has_parallelism:
                # Use pool's fan-out method
                result = await pool.submit_fan_out_and_wait(
                    intents=analysis.parallel_intents,
                    join_intent=analysis.join_intent or user_request,
                    context={"original_request": user_request, **base_context},
                    timeout=request_timeout,
                )
            else:
                # Use pool's sequential method
                result = await pool.submit_and_wait(
                    description=user_request,
                    capabilities=[],  # Let routing figure it out
                    context={"goal": user_request, **base_context},
                    timeout=request_timeout,
                )
        finally:
            if should_shutdown:
                await pool.shutdown(wait=True, timeout=5.0)

        # Convert TaskResult to HandoffResult/PartialResult for synthesis
        if result.success:
            handoff_result = HandoffResult.complete(result.data)
        else:
            handoff_result = PartialResult(
                error=result.error or "Unknown error",
                partial_data=result.data if isinstance(result.data, dict) else {},
            )

        # Synthesize the final response
        return await self._synthesize_response(user_request, handoff_result)

    async def _analyze_request(self, user_request: str) -> RequestAnalysis:
        """Analyze a user request to identify parallelism opportunities.

        Uses LLM reasoning to determine if the request contains multiple
        independent tasks that could be executed in parallel.

        :param user_request: The user's natural language request
        :return: RequestAnalysis with parallelism info
        """
        # Build agent descriptions for the prompt
        agent_descriptions = []
        for agent in self._registry.all_agents():
            if hasattr(agent, "description"):
                agent_descriptions.append(f"- {agent.name}: {agent.description}")
            else:
                agent_descriptions.append(f"- {agent.name}: {', '.join(agent.capabilities)}")

        prompt = f"""Analyze this user request to determine if it contains PARALLEL tasks.

AVAILABLE AGENTS:
{chr(10).join(agent_descriptions)}

USER REQUEST: "{user_request}"

INSTRUCTIONS:
1. Identify if the request asks for MULTIPLE INDEPENDENT tasks of the SAME TYPE
   - Example: "Search channel A AND channel B" = 2 parallel searches
   - Example: "Get transcripts for video X and video Y" = 2 parallel transcript fetches
2. Tasks are parallel if they:
   - Can run independently (don't depend on each other's results)
   - Are the same type of operation (both searches, both transcripts, etc.)
3. Sequential tasks are NOT parallel:
   - "Search, then get transcripts, then summarize" = sequential (each depends on previous)

Respond with JSON only:
{{
    "has_parallelism": true/false,
    "parallel_intents": ["task 1 description", "task 2 description"] or null,
    "join_intent": "what to do after parallel tasks complete" or null,
    "reasoning": "brief explanation"
}}"""

        try:
            response = await self._client.get_response(prompt)
            response_text = response.text.strip()

            # Parse JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)

            if data.get("has_parallelism") and data.get("parallel_intents"):
                return RequestAnalysis.parallel(
                    intents=data["parallel_intents"],
                    join_intent=data.get("join_intent", user_request),
                )
            else:
                return RequestAnalysis.sequential(intent=user_request)

        except (json.JSONDecodeError, KeyError, IndexError):
            # If parsing fails, treat as sequential
            return RequestAnalysis.sequential(intent=user_request)

    async def _synthesize_response(
        self,
        user_request: str,
        result: HandoffResult | PartialResult,
    ) -> str:
        """Synthesize a user-friendly response from the result.

        :param user_request: Original user request
        :param result: Result from agent coordination
        :return: User-friendly response string
        """
        if isinstance(result, PartialResult):
            prompt = f"""The user asked: "{user_request}"

Unfortunately, there was an issue during processing:
Error: {result.error}

Partial data collected: {result.partial_data}

Please explain what happened to the user in a helpful way and suggest alternatives."""

        else:
            prompt = f"""The user asked: "{user_request}"

Here are the results from the specialized agents:
{result.result}

Please present these results to the user in a clear, helpful format.
Summarize key findings and suggest any relevant follow-up actions."""

        # Use client directly for simple response synthesis (no tools needed)
        response = await self._client.get_response(prompt)
        return response.text
