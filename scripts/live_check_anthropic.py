"""Opt-in live smoke check for AnthropicProvider — makes one real API call.

Not part of the pytest suite (lives outside tests/, pytest's testpaths is
scoped to tests/ anyway) and never runs automatically. Run it yourself,
deliberately, when you want to confirm the adapter works against the real
API:

    uv run python scripts/live_check_anthropic.py
    uv run python scripts/live_check_anthropic.py --model claude-haiku-4-5-20251001

Requires ANTHROPIC_API_KEY to be set (.env is loaded automatically).
Costs a small number of real tokens each run.
"""

from __future__ import annotations

import argparse
import asyncio

from devfoundry.providers.anthropic import AnthropicProvider
from devfoundry.providers.types import Message, Role, StreamDone, TextDelta, ToolDefinition


async def main(model: str) -> None:
    provider = AnthropicProvider(default_model=model)

    print(f"--- generate() [{model}] ---")
    result = await provider.generate(
        [Message(role=Role.USER, content="Reply with exactly the word: pong")],
        max_tokens=16,
    )
    print("response:", result.message.content)
    print("stop_reason:", result.stop_reason, "| usage:", result.usage)

    print("\n--- stream() ---")
    chunks: list[str] = []
    async for event in provider.stream(
        [Message(role=Role.USER, content="Count from 1 to 5, one number per line.")],
        max_tokens=64,
    ):
        if isinstance(event, TextDelta):
            chunks.append(event.text)
            print(event.text, end="", flush=True)
        elif isinstance(event, StreamDone):
            print("\n[stream done] stop_reason:", event.result.stop_reason)
    assert chunks, "stream() produced no text deltas"

    print("\n--- tool_call() ---")
    weather_tool = ToolDefinition(
        name="get_weather",
        description="Get the current weather for a city.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    tc_result = await provider.tool_call(
        [Message(role=Role.USER, content="What's the weather in Kolkata?")],
        tools=[weather_tool],
        max_tokens=256,
    )
    print("tool_calls:", tc_result.message.content)

    print("\nAll three methods completed against the live API.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Model ID to use (defaults to a cheap/fast model to keep this check inexpensive).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.model))
