"""End-to-end test script for V1 Orchestrator pattern.

Uses the shared main module functions for consistency with CLI.
Run with: uv run python tests/orchestrator/e2e_test.py
Output: output/test_orchestrator_*.md
"""

import asyncio
import logging
import re
from pathlib import Path

from youtube_agent_orchestrator.application.main import process_request

# Enable logging at INFO level for key components
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logging.getLogger("youtube_agent_orchestrator").setLevel(logging.INFO)

# Expected video IDs from trusted channels
# Note: V1 Orchestrator may not include video IDs in output (LLM decides content)
EXPECTED_VIDEO_IDS = [
    "fI86yXKlnQA",  # Chuds BBQ
    "FsbwQI-EI-k",  # Fork and Embers
]
VIDEO_IDS_REQUIRED = False  # V1 orchestrator doesn't reliably include video sources

# Expected content patterns to verify
EXPECTED_PATTERNS = [
    r"14[0-5].*[°F]",  # Internal temp 140-145°F
    r"2[5-7]5.*[°F]|3[0-5]0.*[°F]",  # Pit temp 250-350°F range
    r"rest",  # Rest mentioned
]


def verify_output(output_path: Path) -> dict:
    """Verify the output file contains expected content."""
    results = {"exists": False, "video_ids": [], "patterns": {}}

    if not output_path.exists():
        return results

    results["exists"] = True
    content = output_path.read_text()

    # Check for expected video IDs
    for vid in EXPECTED_VIDEO_IDS:
        if vid in content:
            results["video_ids"].append(vid)

    # Check for expected content patterns
    for pattern in EXPECTED_PATTERNS:
        results["patterns"][pattern] = bool(re.search(pattern, content, re.IGNORECASE))

    return results


async def main():
    # Standard test request - consistent across runs
    request = """I want to cook a pork loin roast on a Kamado grill/smoker.
I would like some info on how to do this based on techniques on YouTube.
Some channels I trust are fork and embers and chuds bbq.
Ideally, I need to know the temperature, the grill setup, the internal temperature and the time.
Save the results to test_orchestrator_pork_loin.md"""

    print("\n" + "=" * 60)
    print("ORCHESTRATOR PATTERN E2E TEST")
    print("=" * 60)
    print("USER REQUEST:")
    print(request)
    print("=" * 60 + "\n")

    try:
        response = await process_request(request)
        print("\n" + "=" * 60)
        print("FINAL RESPONSE:")
        print("=" * 60)
        print(response)

        # Verify output
        output_path = Path("output/test_orchestrator_pork_loin.md")
        print("\n" + "=" * 60)
        print("VERIFICATION:")
        print("=" * 60)

        results = verify_output(output_path)
        if results["exists"]:
            print(f"✓ Output file exists: {output_path}")
        else:
            # Check for any recent pork loin file
            for f in Path("output").glob("*pork*loin*.md"):
                if f.stat().st_mtime > (asyncio.get_event_loop().time() - 300):
                    print(f"✓ Output file (alternate name): {f}")
                    results = verify_output(f)
                    break
            else:
                print(f"✗ Output file not found: {output_path}")

        # Check video IDs
        found_vids = results.get("video_ids", [])
        if found_vids:
            print(f"✓ Found expected videos: {found_vids}")
        elif VIDEO_IDS_REQUIRED:
            print(f"✗ Expected video IDs not found: {EXPECTED_VIDEO_IDS}")
        else:
            print("○ Video IDs not in output (optional for this pattern)")

        # Check content patterns
        patterns = results.get("patterns", {})
        for pattern, found in patterns.items():
            status = "✓" if found else "✗"
            print(f"{status} Pattern '{pattern}': {'found' if found else 'NOT found'}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
