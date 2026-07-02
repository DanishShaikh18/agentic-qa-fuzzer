"""
CLI Entrypoint for the Agentic QA Fuzzer.

Wires together `config.py` (environment/settings) and `agent.py` (the LangGraph
ReAct loop over MCP tools) into a single runnable command. This is the file
the Docker container's ENTRYPOINT / CMD should invoke.

Usage:
    python cli.py
    python cli.py --target-url http://victim-api:8000
"""

import argparse
import asyncio
import sys
from pathlib import Path

from langchain_core.messages import AIMessage

# Ensure fuzzer-agent/src/ is importable when running cli.py directly
_src_dir = str(Path(__file__).resolve().parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

try:
    from .agent import run_fuzzer
    from .config import settings
except ImportError:
    from agent import run_fuzzer
    from config import settings



def parse_args() -> argparse.Namespace:
    """Parses CLI arguments, falling back to config defaults when not provided."""
    parser = argparse.ArgumentParser(
        description="Agentic QA Fuzzer — autonomous LLM-driven API vulnerability discovery."
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default=settings.TARGET_API_URL,
        help=f"Root URL of the target microservice (default: {settings.TARGET_API_URL})",
    )
    return parser.parse_args()


def print_banner(target_url: str) -> None:
    print("=" * 70)
    print("  AGENTIC QA FUZZER — Autonomous API Vulnerability Discovery")
    print("=" * 70)
    print(f"  Target:          {target_url}")
    print(f"  Recursion limit: {settings.MAX_RECURSION_LIMIT}")
    print("=" * 70)
    print()


def print_summary(final_state: dict) -> None:
    """Extracts and prints the final AI-generated vulnerability report from graph state."""
    messages = final_state.get("messages", [])

    tool_calls_made = sum(
        len(getattr(m, "tool_calls", []) or []) for m in messages
    )

    last_ai_message = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) and m.content),
        None,
    )

    print()
    print("-" * 70)
    print("  FUZZING SESSION COMPLETE")
    print("-" * 70)
    print(f"  Total tool calls executed: {tool_calls_made}")
    print("-" * 70)

    if last_ai_message is not None:
        print("\n[Final Report from Agent]\n")
        print(last_ai_message.content)
    else:
        print("\n[!] Agent produced no final text report. Check message history for details.")
    print()


async def main_async() -> int:
    args = parse_args()
    print_banner(args.target_url)

    try:
        final_state = await run_fuzzer(args.target_url)
    except Exception as exc:
        print(f"[!] Fuzzing session terminated with an unhandled error: {exc}", file=sys.stderr)
        return 1

    print_summary(final_state)
    return 0


def main() -> None:
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()