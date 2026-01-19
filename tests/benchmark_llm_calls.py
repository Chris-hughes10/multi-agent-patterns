"""Benchmark script for measuring LLM calls across different agent patterns.

This script runs each agent pattern (V1 Orchestrator, V2 Autonomous, V3 Planner)
multiple times and counts the LLM calls made during each run.

Key features:
- Clears transcript cache between runs for consistent comparisons
- Uses middleware to accurately count LLM calls
- Patches the existing get_chat_client to add counting middleware
- Runs configurable number of iterations per pattern
- Outputs structured results for analysis

Run with: uv run python tests/benchmark_llm_calls.py
"""

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_framework import ChatMiddleware
from agent_framework._middleware import ChatContext


# ============================================================================
# LLM Call Counter Middleware
# ============================================================================


class LLMCallCounter(ChatMiddleware):
    """Middleware that counts LLM API calls.

    This middleware intercepts all chat client requests and increments a counter.
    It's injected into the standard get_chat_client() to track all LLM usage.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    def reset(self) -> None:
        """Reset the counter for a new benchmark run."""
        self.call_count = 0
        self.calls = []

    async def process(
        self,
        context: ChatContext,
        next: Callable[[ChatContext], Awaitable[None]],
    ) -> None:
        """Count each LLM call as it passes through."""
        self.call_count += 1

        call_info = {
            "call_number": self.call_count,
            "timestamp": datetime.now().isoformat(),
            "message_count": len(context.messages) if context.messages else 0,
        }
        self.calls.append(call_info)

        # Continue to the actual LLM call
        await next(context)


# Global counter instance
_counter = LLMCallCounter()


def get_call_counter() -> LLMCallCounter:
    """Get the global LLM call counter."""
    return _counter


# ============================================================================
# Client Patching (wraps the real get_chat_client)
# ============================================================================


@contextmanager
def patch_client_with_counter():
    """Context manager that patches get_chat_client to add counting middleware.

    This wraps the original get_chat_client function to add our counter middleware
    to the client it returns. The original client creation logic is preserved.
    """
    import youtube_agent_orchestrator.infra.client as client_module

    # Save original function
    original_get_chat_client = client_module.get_chat_client

    # Clear the cache so we get a fresh client
    original_get_chat_client.cache_clear()

    @lru_cache
    def counting_get_chat_client():
        """Wrapper that gets the real client and adds counting middleware."""
        # Create client using original logic (without lru_cache wrapper)
        from agent_framework.azure import AzureOpenAIChatClient
        from azure.identity import AzureCliCredential
        from youtube_agent_orchestrator.models.config import get_settings

        settings = get_settings()

        if not settings.is_configured:
            raise ValueError(
                "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_DEPLOYMENT environment variables."
            )

        credential_kwargs = {}
        if settings.azure_tenant_id:
            credential_kwargs["tenant_id"] = settings.azure_tenant_id

        credential = AzureCliCredential(**credential_kwargs)

        client = AzureOpenAIChatClient(
            credential=credential,
            endpoint=settings.azure_openai_endpoint,
            deployment_name=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            temperature=settings.llm_temperature,
            seed=settings.llm_seed,
        )

        # Add our counting middleware
        client.middleware = [_counter]

        return client

    # Replace the module's function
    client_module.get_chat_client = counting_get_chat_client

    try:
        yield
    finally:
        # Restore original function
        client_module.get_chat_client = original_get_chat_client
        # Clear any caches
        original_get_chat_client.cache_clear()


# ============================================================================
# Cache Management
# ============================================================================


def clear_transcript_cache() -> int:
    """Clear all cached transcripts and return count of files removed."""
    cache_dir = Path("data/transcripts")
    if not cache_dir.exists():
        return 0

    files = list(cache_dir.glob("*.json"))
    count = len(files)

    for f in files:
        f.unlink()

    return count


# ============================================================================
# Benchmark Runner
# ============================================================================


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    pattern: str
    run_number: int
    llm_calls: int
    duration_ms: float
    success: bool
    error: str | None = None
    call_details: list[dict] = field(default_factory=list)


@dataclass
class BenchmarkSummary:
    """Summary statistics for a pattern."""
    pattern: str
    runs: int
    min_calls: int
    max_calls: int
    avg_calls: float
    std_dev: float
    all_results: list[BenchmarkResult] = field(default_factory=list)


async def run_orchestrator_pattern(request: str) -> str:
    """Run the V1 Orchestrator pattern."""
    from youtube_agent_orchestrator.cli.main import process_request
    return await process_request(request)


async def run_autonomous_pattern(request: str, timeout: float = 180.0) -> str:
    """Run the V2 Autonomous pattern."""
    from youtube_goal_agents.cli.main import process_request
    return await process_request(request, timeout=timeout)


async def run_planner_pattern(request: str) -> str:
    """Run the V3 Planner pattern."""
    from youtube_agent_planner.cli.main import process_request
    return await process_request(request)


async def run_single_benchmark(
    pattern_name: str,
    runner: Callable[[str], Awaitable[str]],
    request: str,
    run_number: int,
) -> BenchmarkResult:
    """Run a single benchmark iteration."""
    import time

    # Reset counter
    counter = get_call_counter()
    counter.reset()

    start_time = time.perf_counter()

    try:
        # Use patched client with counter middleware
        with patch_client_with_counter():
            await runner(request)
        success = True
        error = None

    except Exception as e:
        success = False
        error = str(e)

    end_time = time.perf_counter()
    duration_ms = (end_time - start_time) * 1000

    return BenchmarkResult(
        pattern=pattern_name,
        run_number=run_number,
        llm_calls=counter.call_count,
        duration_ms=duration_ms,
        success=success,
        error=error,
        call_details=counter.calls.copy(),
    )


def calculate_summary(pattern: str, results: list[BenchmarkResult]) -> BenchmarkSummary:
    """Calculate summary statistics for a pattern's results."""
    import statistics

    successful = [r for r in results if r.success]
    if not successful:
        return BenchmarkSummary(
            pattern=pattern,
            runs=len(results),
            min_calls=0,
            max_calls=0,
            avg_calls=0.0,
            std_dev=0.0,
            all_results=results,
        )

    call_counts = [r.llm_calls for r in successful]

    return BenchmarkSummary(
        pattern=pattern,
        runs=len(results),
        min_calls=min(call_counts),
        max_calls=max(call_counts),
        avg_calls=statistics.mean(call_counts),
        std_dev=statistics.stdev(call_counts) if len(call_counts) > 1 else 0.0,
        all_results=results,
    )


# ============================================================================
# Main Benchmark
# ============================================================================


def get_request_for_pattern(pattern_key: str) -> str:
    """Get the standard test request for a pattern (matches e2e tests exactly)."""
    # Base request - same as e2e tests
    base = """I want to cook a pork loin roast on a Kamado grill/smoker.
I would like some info on how to do this based on techniques on YouTube.
Some channels I trust are fork and embers and chuds bbq.
Ideally, I need to know the temperature, the grill setup, the internal temperature and the time.
Save the results to """

    # Pattern-specific output files (matching e2e tests)
    output_files = {
        "v1": "test_orchestrator_pork_loin.md",
        "v2": "test_goal_aware_pork_loin.md",
        "v3": "test_planner_pork_loin.md",
    }

    return base + output_files.get(pattern_key, "benchmark_output.md")


async def run_benchmark(
    num_runs: int = 3,
    patterns: list[str] | None = None,
    clear_cache: bool = True,
) -> dict[str, BenchmarkSummary]:
    """Run the full benchmark suite.

    Args:
        num_runs: Number of times to run each pattern
        patterns: Which patterns to test ('v1', 'v2', 'v3'). Default is all.
        clear_cache: Whether to clear transcript cache between runs

    Returns:
        Dictionary mapping pattern names to their summary statistics.
    """
    if patterns is None:
        patterns = ["v1", "v2", "v3"]

    pattern_runners = {
        "v1": ("V1 Orchestrator", run_orchestrator_pattern),
        "v2": ("V2 Autonomous", run_autonomous_pattern),
        "v3": ("V3 Planner", run_planner_pattern),
    }

    results: dict[str, list[BenchmarkResult]] = {p: [] for p in patterns}

    print("\n" + "=" * 70)
    print("LLM CALL BENCHMARK")
    print("=" * 70)
    print(f"Patterns: {', '.join(patterns)}")
    print(f"Runs per pattern: {num_runs}")
    print(f"Clear cache between runs: {clear_cache}")
    print("=" * 70 + "\n")

    for pattern_key in patterns:
        if pattern_key not in pattern_runners:
            print(f"Unknown pattern: {pattern_key}")
            continue

        pattern_name, runner = pattern_runners[pattern_key]

        print(f"\n--- {pattern_name} ---")

        for run_num in range(1, num_runs + 1):
            print(f"  Run {run_num}/{num_runs}...", end=" ", flush=True)

            if clear_cache:
                cleared = clear_transcript_cache()
                if cleared > 0:
                    print(f"(cleared {cleared} cached transcripts)", end=" ", flush=True)

            request = get_request_for_pattern(pattern_key)
            result = await run_single_benchmark(
                pattern_name, runner, request, run_num
            )
            results[pattern_key].append(result)

            if result.success:
                print(f"LLM calls: {result.llm_calls}, Duration: {result.duration_ms:.0f}ms")
            else:
                print(f"FAILED: {result.error}")

    # Calculate summaries
    summaries = {
        key: calculate_summary(pattern_runners[key][0], res)
        for key, res in results.items()
    }

    return summaries


def print_summary(summaries: dict[str, BenchmarkSummary]) -> None:
    """Print a formatted summary of benchmark results."""
    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    for key, summary in summaries.items():
        print(f"\n{summary.pattern}:")
        print(f"  Runs: {summary.runs}")
        print(f"  LLM Calls: min={summary.min_calls}, max={summary.max_calls}, avg={summary.avg_calls:.1f}")
        print(f"  Std Dev: {summary.std_dev:.2f}")

        # Show individual run details
        print("  Individual runs:")
        for r in summary.all_results:
            status = "OK" if r.success else f"FAIL: {r.error}"
            print(f"    Run {r.run_number}: {r.llm_calls} calls, {r.duration_ms:.0f}ms - {status}")

    print("\n" + "=" * 70)

    # Show comparison table
    print("\nCOMPARISON TABLE:")
    print("-" * 50)
    print(f"{'Pattern':<20} {'Avg Calls':<12} {'Range':<15} {'Std Dev':<10}")
    print("-" * 50)
    for summary in summaries.values():
        range_str = f"{summary.min_calls}-{summary.max_calls}"
        print(f"{summary.pattern:<20} {summary.avg_calls:<12.1f} {range_str:<15} {summary.std_dev:<10.2f}")
    print("-" * 50)


def save_results(summaries: dict[str, BenchmarkSummary], output_path: str = "output/benchmark_results.json") -> None:
    """Save benchmark results to a JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Convert to serializable format
    data = {
        "timestamp": datetime.now().isoformat(),
        "summaries": {}
    }

    for key, summary in summaries.items():
        data["summaries"][key] = {
            "pattern": summary.pattern,
            "runs": summary.runs,
            "min_calls": summary.min_calls,
            "max_calls": summary.max_calls,
            "avg_calls": summary.avg_calls,
            "std_dev": summary.std_dev,
            "results": [
                {
                    "run": r.run_number,
                    "llm_calls": r.llm_calls,
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                    "call_details": r.call_details,
                }
                for r in summary.all_results
            ]
        }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nResults saved to: {output_path}")


async def main():
    """Main entry point for the benchmark."""
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark LLM calls across agent patterns")
    parser.add_argument("-n", "--num-runs", type=int, default=3, help="Number of runs per pattern")
    parser.add_argument("-p", "--patterns", nargs="+", choices=["v1", "v2", "v3"],
                       help="Patterns to test (default: all)")
    parser.add_argument("--no-cache-clear", action="store_true",
                       help="Don't clear transcript cache between runs")
    parser.add_argument("-o", "--output", default="output/benchmark_results.json",
                       help="Output file for results")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Enable verbose logging to see agent decisions")

    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        # Enable debug for our agents
        logging.getLogger("youtube_agent").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    try:
        summaries = await run_benchmark(
            num_runs=args.num_runs,
            patterns=args.patterns,
            clear_cache=not args.no_cache_clear,
        )

        print_summary(summaries)
        save_results(summaries, args.output)

    except Exception as e:
        print(f"\nBenchmark failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
