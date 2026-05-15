"""SynthesizerAgent - User-facing entry point for multi-agent coordination.

The Synthesizer is the single point of contact for users. It:
- Receives all user messages
- Analyzes requests for parallelism opportunities
- Delegates to DispatcherPool for agent coordination
- Aggregates results and produces the final user-facing response

The Synthesizer is a thin wrapper that uses the pool's coordination methods,
just like any agent would for fan-out operations.
"""

import json
from typing import TYPE_CHECKING

from agent_framework import Agent, Message
from agent_framework.openai import OpenAIChatClient

from youtube_agent_orchestrator.infra.client import get_chat_client, get_default_options
from youtube_goal_agents.infra.pool import DispatcherPool
from youtube_goal_agents.models.handoff import (
    HandoffResult,
    PartialResult,
    RequestAnalysis,
)

if TYPE_CHECKING:
    from youtube_goal_agents.infra.registry import AgentRegistry


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


PARALLELISM_ANALYSIS_PROMPT = """Analyze this user request to determine if it contains PARALLEL tasks.

AVAILABLE AGENTS:
{agent_descriptions}

USER REQUEST: "{user_request}"

INSTRUCTIONS:
1. ONLY the FIRST step can be parallelized. Later steps (transcripts, summaries, file writing) depend on earlier results.
2. Parallel tasks must be:
   - The SAME type of operation (e.g., all searches)
   - Completely independent (no task needs another's output)
   - The FIRST step in the workflow
3. CRITICAL: "Find 2 videos, get transcripts, summarize" means:
   - Parallel: 2 search tasks (finding the videos)
   - Join: "fetch transcripts and summarize" (sequential AFTER searches complete)
   - DO NOT parallelize transcript/summarize - they need search results first!
4. Common patterns:
   - "Find X and Y" → 2 parallel searches, join handles the rest
   - "Get transcripts for video A and B" (IDs given) → 2 parallel transcript fetches
   - "Search, transcript, summarize" → NO parallelism (sequential chain)

Respond with JSON only:
{{
    "has_parallelism": true/false,
    "parallel_intents": ["search task 1", "search task 2"] or null,
    "join_intent": "what to do after parallel tasks complete (e.g., fetch transcripts and summarize)" or null,
    "reasoning": "brief explanation"
}}"""


ERROR_RESPONSE_PROMPT = """The user asked: "{user_request}"

The agent workflow encountered an error:
Error: {error}

Partial data collected (if any): {partial_data}

CRITICAL INSTRUCTIONS:
1. Be HONEST about what failed - do not claim capabilities you don't have
2. Report the ACTUAL error message above
3. If partial data was collected, present what DID work
4. DO NOT hallucinate fake results or claim you "can't search YouTube" if the error is something else
5. Suggest specific alternatives based on the actual error

Format: Clearly explain what went wrong and what partial results (if any) are available."""


SUCCESS_RESPONSE_PROMPT = """The user asked: "{user_request}"

Here are the ACTUAL results from the specialized agents:
{result}

CRITICAL INSTRUCTIONS:
1. Present ONLY the information that appears in the results above
2. DO NOT claim you "can't" do something - the agents ALREADY DID the work
3. DO NOT hallucinate or make up information not in the results
4. If results contain summaries, present those summaries
5. If results contain file paths, tell the user where the file was saved
6. If results contain video IDs or titles, include them

Format your response clearly, highlighting:
- What was accomplished
- Key findings from the results
- Any files created (with paths)
- Suggested follow-up actions if relevant"""


class SynthesizerAgent:
    """User-facing agent that coordinates multi-agent workflows.

    The Synthesizer is a thin entry point that:
    1. Analyzes requests for parallelism (LLM-based)
    2. Delegates to DispatcherPool for all coordination
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
        client: OpenAIChatClient | None = None,
        timeout: float = 120.0,
        pool: DispatcherPool | None = None,
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
        self._chat_agent: Agent | None = None
        self._external_pool = pool  # None = create per request (CLI mode)

    @property
    def name(self) -> str:
        """Return agent name."""
        return "synthesizer"

    def _get_chat_agent(self) -> Agent:
        """Get or create the Agent for response synthesis."""
        if self._chat_agent is None:
            self._chat_agent = Agent(
                client=self._client,
                name=self.name,
                instructions=SYNTHESIZER_INSTRUCTIONS,
                tools=[],
                default_options=get_default_options(),
            )
        return self._chat_agent

    async def _get_pool(self) -> tuple[DispatcherPool, bool]:
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
        pool = DispatcherPool(self._registry)
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
        agent_desc_list = []
        for agent in self._registry.all_agents():
            if hasattr(agent, "description"):
                agent_desc_list.append(f"- {agent.name}: {agent.description}")
            else:
                agent_desc_list.append(f"- {agent.name}: {', '.join(agent.capabilities)}")

        prompt = PARALLELISM_ANALYSIS_PROMPT.format(
            agent_descriptions="\n".join(agent_desc_list),
            user_request=user_request,
        )

        try:
            response = await self._client.get_response([Message(role="user", contents=[prompt])])
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
            prompt = ERROR_RESPONSE_PROMPT.format(
                user_request=user_request,
                error=result.error,
                partial_data=result.partial_data,
            )
        else:
            prompt = SUCCESS_RESPONSE_PROMPT.format(
                user_request=user_request,
                result=result.result,
            )

        # Use client directly for simple response synthesis (no tools needed)
        response = await self._client.get_response([Message(role="user", contents=[prompt])])
        return response.text
