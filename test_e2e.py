"""End-to-end test script for parallel execution via Synthesizer.

Uses the shared main module functions for consistency with CLI.
"""

import asyncio
import logging

from youtube_autonomous_agents.application.main import process_request

# Enable logging at INFO level for key components
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Set specific loggers to INFO to see key events
logging.getLogger("youtube_autonomous_agents.self_selection").setLevel(logging.INFO)
logging.getLogger("youtube_autonomous_agents.agents.search").setLevel(logging.INFO)
logging.getLogger("youtube_autonomous_agents.agents.transcript").setLevel(logging.INFO)
logging.getLogger("youtube_autonomous_agents.agents.summarize").setLevel(logging.INFO)
logging.getLogger("youtube_autonomous_agents.agents.writer").setLevel(logging.INFO)


async def main():
    # The request that should trigger parallel searches AND write to file
    request = """I want to cook a pork loin roast on a Kamado grill/smoker. I would like some info on how to do this based on techniques on YouTube. Some channels I trust are fork and embers and chuds bbq. Ideally, I need to know the temperature, the grill setup, the internal temperature and the time. Save the results to pork_loin_research.md"""

    print("\n" + "=" * 60)
    print("USER REQUEST:")
    print("=" * 60)
    print(request)
    print("=" * 60 + "\n")

    try:
        response = await process_request(request, timeout=180.0)
        print("\n" + "=" * 60)
        print("FINAL RESPONSE:")
        print("=" * 60)
        print(response)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
