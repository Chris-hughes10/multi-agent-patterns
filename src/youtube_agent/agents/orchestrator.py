"""Orchestrator Agent - coordinates all sub-agents."""

import asyncio
import logging
from typing import Annotated

from agent_framework import ChatAgent
from agent_framework._threads import AgentThread
from pydantic import Field

from youtube_agent.agents.client import get_chat_client
from youtube_agent.agents.context import TranscriptContextProvider
from youtube_agent.agents.search_agent import create_search_agent
from youtube_agent.agents.summarize_agent import create_summarize_agent
from youtube_agent.agents.transcript_agent import create_transcript_agent

logger = logging.getLogger("youtube_agent.orchestrator")

ORCHESTRATOR_INSTRUCTIONS = """You are the Orchestrator Agent for a YouTube research system. You coordinate specialized agents to help users research topics using YouTube videos.

Your available agents:
1. **SearchAgent** - Searches YouTube for videos on a topic
2. **TranscriptAgent** - Fetches, stores, and retrieves video transcripts (the ONLY agent that fetches from YouTube)
3. **SummarizeAgent** - Summarizes text or stored transcripts (does NOT fetch)

## Memory: Available Transcripts
You have access to a memory section called "Available Transcripts" that shows all stored transcripts.
ALWAYS check this memory first before searching YouTube - you may already have the data you need!

## How to handle requests:

**For questions about specific content (e.g., "what did X say about Y"):**
→ Check your "Available Transcripts" memory for relevant videos
→ If relevant transcripts exist, use TranscriptAgent to look up the specific video and search within it
→ Only search YouTube if no relevant stored transcripts are found in memory

**For "search for videos about X":**
→ Use SearchAgent to find relevant videos

**For "get transcript for video X":**
→ Use TranscriptAgent to fetch the transcript (automatically uses cache if available)

**For "summarize video X":**
→ FIRST use TranscriptAgent to fetch/retrieve the transcript
→ THEN use SummarizeAgent to summarize the text returned by TranscriptAgent

**For "research topic X" or "what do YouTube videos say about X":**
1. Check "Available Transcripts" memory - you may already have relevant data!
2. Use SearchAgent to find new videos on the topic (if needed)
3. Use TranscriptAgent to fetch transcripts (it will use cache when available)
4. Pass the transcript text to SummarizeAgent to summarize
5. Synthesize the summaries into a comprehensive answer

## IMPORTANT: Workflow for summarization
The SummarizeAgent cannot fetch transcripts itself. Always:
1. Get transcript text via TranscriptAgent first
2. Pass that text to SummarizeAgent

## Response guidelines:
- CHECK YOUR MEMORY for stored transcripts before doing new searches
- TranscriptAgent automatically uses cached transcripts when available
- Decide the output format based on user intent (detailed vs concise)
- For research queries, synthesize insights from multiple videos
- Always cite which videos information came from
- If a step fails, explain what happened and continue with available data"""


class OrchestratorAgent:
    """Orchestrator that coordinates sub-agents for YouTube research.

    This class manages the lifecycle of sub-agents and provides
    tool wrappers that the orchestrator can use to delegate work.

    The orchestrator maintains conversation memory via an AgentThread,
    and uses a TranscriptContextProvider to inject information about
    stored transcripts before each agent call.
    """

    def __init__(self) -> None:
        """Initialize the orchestrator with sub-agents."""
        self._search_agent: ChatAgent | None = None
        self._transcript_agent: ChatAgent | None = None
        self._summarize_agent: ChatAgent | None = None
        self._orchestrator: ChatAgent | None = None
        self._thread: AgentThread | None = None
        self._context_provider: TranscriptContextProvider | None = None

    def _get_search_agent(self) -> ChatAgent:
        """Lazy initialization of search agent."""
        if self._search_agent is None:
            self._search_agent = create_search_agent()
        return self._search_agent

    def _get_transcript_agent(self) -> ChatAgent:
        """Lazy initialization of transcript agent."""
        if self._transcript_agent is None:
            self._transcript_agent = create_transcript_agent()
        return self._transcript_agent

    def _get_summarize_agent(self) -> ChatAgent:
        """Lazy initialization of summarize agent."""
        if self._summarize_agent is None:
            self._summarize_agent = create_summarize_agent()
        return self._summarize_agent

    def _run_sync(self, coro: asyncio.coroutines) -> str:
        """Run an async coroutine synchronously.

        Handles the case where we're already in an event loop.
        """
        try:
            asyncio.get_running_loop()
            # We're in an async context, need to use a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No running loop, safe to use asyncio.run
            return asyncio.run(coro)

    def ask_search_agent(
        self,
        request: Annotated[str, Field(description="Request for the Search Agent")],
    ) -> str:
        """Delegate a search request to the Search Agent.

        Use this to find YouTube videos about a topic.

        :param request: What to search for (e.g., "Find videos about RAG best practices")
        :return: Search results from the agent
        """
        logger.debug("SearchAgent called with: %s", request)
        agent = self._get_search_agent()

        async def _run() -> str:
            result = await agent.run(request)
            logger.debug("SearchAgent response: %s", result.text[:200] if result.text else "empty")
            return result.text

        return self._run_sync(_run())

    def ask_transcript_agent(
        self,
        request: Annotated[str, Field(description="Request for the Transcript Agent")],
    ) -> str:
        """Delegate a transcript request to the Transcript Agent.

        Use this to fetch, store, or look up video transcripts.

        :param request: What to do (e.g., "Fetch transcript for video dQw4w9WgXcQ")
        :return: Response from the transcript agent
        """
        logger.debug("TranscriptAgent called with: %s", request)
        agent = self._get_transcript_agent()

        async def _run() -> str:
            result = await agent.run(request)
            logger.debug(
                "TranscriptAgent response: %s", result.text[:200] if result.text else "empty"
            )
            return result.text

        return self._run_sync(_run())

    def ask_summarize_agent(
        self,
        request: Annotated[str, Field(description="Request for the Summarize Agent")],
    ) -> str:
        """Delegate a summarization request to the Summarize Agent.

        Use this to summarize videos or text.

        :param request: What to summarize (e.g., "Summarize video dQw4w9WgXcQ")
        :return: Summary from the agent
        """
        logger.debug("SummarizeAgent called with: %s", request)
        agent = self._get_summarize_agent()

        async def _run() -> str:
            result = await agent.run(request)
            logger.debug(
                "SummarizeAgent response: %s", result.text[:200] if result.text else "empty"
            )
            return result.text

        return self._run_sync(_run())

    def get_orchestrator(self) -> ChatAgent:
        """Get the orchestrator ChatAgent.

        :return: Configured ChatAgent that can coordinate sub-agents
        """
        if self._orchestrator is None:
            client = get_chat_client()
            self._orchestrator = ChatAgent(
                chat_client=client,
                name="Orchestrator",
                instructions=ORCHESTRATOR_INSTRUCTIONS,
                tools=[
                    self.ask_search_agent,
                    self.ask_transcript_agent,
                    self.ask_summarize_agent,
                ],
            )
        return self._orchestrator

    def _get_context_provider(self) -> TranscriptContextProvider:
        """Lazy initialization of context provider."""
        if self._context_provider is None:
            self._context_provider = TranscriptContextProvider()
        return self._context_provider

    async def run(self, user_request: str) -> str:
        """Run the orchestrator with a user request.

        Uses the same AgentThread across calls to maintain conversation memory,
        and a TranscriptContextProvider to inject context about stored transcripts.

        :param user_request: The user's request
        :return: The orchestrator's response
        """
        logger.debug("Orchestrator received request: %s", user_request)
        orchestrator = self.get_orchestrator()

        # Create thread on first run with context provider, reuse for conversation memory
        if self._thread is None:
            context_provider = self._get_context_provider()
            self._thread = orchestrator.get_new_thread(context_provider=context_provider)

        logger.debug("Calling Azure OpenAI...")
        result = await orchestrator.run(user_request, thread=self._thread)
        logger.debug("Orchestrator completed")
        return result.text

    def reset_conversation(self) -> None:
        """Reset the conversation memory and context.

        Call this to start a fresh conversation without previous context.
        """
        self._thread = None
        if self._context_provider is not None:
            self._context_provider.reset()


def create_orchestrator() -> OrchestratorAgent:
    """Create an OrchestratorAgent instance.

    :return: Configured OrchestratorAgent
    """
    return OrchestratorAgent()
