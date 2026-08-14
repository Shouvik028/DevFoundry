"""Mocked tests for AnthropicProvider. No network calls, no API credits —
the `anthropic` SDK client is faked out entirely. See
scripts/live_check_anthropic.py for the opt-in real-API smoke check."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from devfoundry.providers.anthropic import AnthropicProvider, _to_anthropic_messages
from devfoundry.providers.base import NoToolCallError, ProviderError
from devfoundry.providers.types import (
    Message,
    Role,
    StopReason,
    StreamDone,
    TextBlock,
    TextDelta,
    ToolCallDelta,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)


def make_response(*, content, stop_reason="end_turn", model="claude-test-model"):
    """Build a fake object matching the bits of anthropic's Message
    response our adapter actually reads."""
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def text_block(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def tool_use_block(id_: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def make_provider(client) -> AnthropicProvider:
    return AnthropicProvider(client=client, default_model="claude-test-model")


# --- generate() -----------------------------------------------------------


async def test_generate_text_only():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_response(content=[text_block("Looks good to me.")])
    )
    provider = make_provider(client)

    result = await provider.generate([Message(role=Role.USER, content="Review this diff.")])

    assert result.message.role == Role.ASSISTANT
    assert result.message.content == "Looks good to me."
    assert result.stop_reason == StopReason.END_TURN
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.model == "claude-test-model"

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": "Review this diff."}]
    assert "tools" not in kwargs


async def test_generate_maps_tool_use_blocks():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_response(
            content=[tool_use_block("call_1", "git_diff", {"path": "."})],
            stop_reason="tool_use",
        )
    )
    provider = make_provider(client)
    tools = [ToolDefinition(name="git_diff", description="Show a diff", input_schema={})]

    result = await provider.generate(
        [Message(role=Role.USER, content="What changed?")], tools=tools
    )

    assert result.stop_reason == StopReason.TOOL_USE
    assert isinstance(result.message.content, list)
    assert result.message.content == [ToolUseBlock(id="call_1", name="git_diff", input={"path": "."})]

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [{"name": "git_diff", "description": "Show a diff", "input_schema": {}}]


async def test_generate_wraps_sdk_errors():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=anthropic.AnthropicError("boom"))
    provider = make_provider(client)

    with pytest.raises(ProviderError):
        await provider.generate([Message(role=Role.USER, content="hi")])


async def test_generate_requires_a_model():
    client = MagicMock()
    provider = AnthropicProvider(client=client)  # no default_model

    with pytest.raises(ProviderError):
        await provider.generate([Message(role=Role.USER, content="hi")])
    client.messages.create.assert_not_called()


# --- tool_call() ------------------------------------------------------


async def test_tool_call_returns_tool_use():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_response(
            content=[tool_use_block("call_1", "route", {"agent": "reviewer"})],
            stop_reason="tool_use",
        )
    )
    provider = make_provider(client)
    tools = [ToolDefinition(name="route", description="Pick an agent", input_schema={})]

    result = await provider.tool_call([Message(role=Role.USER, content="Who handles this?")], tools)

    assert result.stop_reason == StopReason.TOOL_USE
    assert result.message.content == [ToolUseBlock(id="call_1", name="route", input={"agent": "reviewer"})]

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "any"}
    assert kwargs["temperature"] == 0.0


async def test_tool_call_with_explicit_tool_choice():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_response(
            content=[tool_use_block("call_1", "route", {})], stop_reason="tool_use"
        )
    )
    provider = make_provider(client)
    tools = [ToolDefinition(name="route", description="Pick an agent", input_schema={})]

    await provider.tool_call(
        [Message(role=Role.USER, content="hi")], tools, tool_choice="route"
    )

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "route"}


async def test_tool_call_raises_when_model_answers_with_text():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_response(content=[text_block("I'd rather just tell you.")])
    )
    provider = make_provider(client)
    tools = [ToolDefinition(name="route", description="Pick an agent", input_schema={})]

    with pytest.raises(NoToolCallError):
        await provider.tool_call([Message(role=Role.USER, content="hi")], tools)


async def test_tool_call_requires_at_least_one_tool():
    provider = make_provider(MagicMock())

    with pytest.raises(ProviderError):
        await provider.tool_call([Message(role=Role.USER, content="hi")], [])


# --- stream() -----------------------------------------------------------


class FakeStreamContext:
    """Fakes the async context manager anthropic's `messages.stream(...)`
    returns: async-iterable of events, plus get_final_message()."""

    def __init__(self, events, final_message):
        self._events = events
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self._events:
            yield event

    async def get_final_message(self):
        return self._final_message


async def test_stream_yields_deltas_then_done():
    events = [
        SimpleNamespace(
            type="content_block_start", index=0, content_block=SimpleNamespace(type="text")
        ),
        SimpleNamespace(
            type="content_block_delta", index=0, delta=SimpleNamespace(type="text_delta", text="Looks ")
        ),
        SimpleNamespace(
            type="content_block_delta", index=0, delta=SimpleNamespace(type="text_delta", text="good.")
        ),
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(type="tool_use", id="call_1", name="git_diff"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"path"'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='":"."}'),
        ),
    ]
    final = make_response(
        content=[text_block("Looks good."), tool_use_block("call_1", "git_diff", {"path": "."})],
        stop_reason="tool_use",
    )
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=FakeStreamContext(events, final))
    provider = make_provider(client)

    collected = [event async for event in provider.stream([Message(role=Role.USER, content="hi")])]

    text_deltas = [e for e in collected if isinstance(e, TextDelta)]
    tool_deltas = [e for e in collected if isinstance(e, ToolCallDelta)]
    done = [e for e in collected if isinstance(e, StreamDone)]

    assert [d.text for d in text_deltas] == ["Looks ", "good."]
    assert tool_deltas[0].id == "call_1"
    assert tool_deltas[0].name == "git_diff"
    assert "".join(d.partial_json for d in tool_deltas) == '{"path"":"."}'
    assert len(done) == 1
    assert done[0].result.stop_reason == StopReason.TOOL_USE
    assert done[0].result.message.content == [
        TextBlock(text="Looks good."),
        ToolUseBlock(id="call_1", name="git_diff", input={"path": "."}),
    ]


async def test_stream_wraps_sdk_errors():
    client = MagicMock()

    class ExplodingStreamContext(FakeStreamContext):
        async def __aenter__(self):
            raise anthropic.AnthropicError("connection reset")

    client.messages.stream = MagicMock(return_value=ExplodingStreamContext([], None))
    provider = make_provider(client)

    with pytest.raises(ProviderError):
        [event async for event in provider.stream([Message(role=Role.USER, content="hi")])]


# --- message conversion helpers ----------------------------------------


def test_to_anthropic_messages_extracts_system_and_merges_tool_results():
    messages = [
        Message(role=Role.SYSTEM, content="You are a careful reviewer."),
        Message(role=Role.USER, content="Review this."),
        Message(
            role=Role.ASSISTANT,
            content=[ToolUseBlock(id="call_1", name="git_diff", input={})],
        ),
        Message(role=Role.TOOL, content=[ToolResultBlock(tool_use_id="call_1", content="+1 -1")]),
        Message(role=Role.TOOL, content=[ToolResultBlock(tool_use_id="call_2", content="ok")]),
    ]

    anthropic_messages, system = _to_anthropic_messages(messages)

    assert system == "You are a careful reviewer."
    assert anthropic_messages[0] == {"role": "user", "content": "Review this."}
    assert anthropic_messages[1]["role"] == "assistant"
    assert anthropic_messages[1]["content"] == [
        {"type": "tool_use", "id": "call_1", "name": "git_diff", "input": {}}
    ]
    # Both TOOL messages merge into a single user turn.
    assert anthropic_messages[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "+1 -1", "is_error": False},
            {"type": "tool_result", "tool_use_id": "call_2", "content": "ok", "is_error": False},
        ],
    }
    assert len(anthropic_messages) == 3


def test_to_anthropic_messages_rejects_string_content_on_tool_role():
    with pytest.raises(ProviderError):
        _to_anthropic_messages([Message(role=Role.TOOL, content="not a block list")])
