"""Anthropic implementation of the ModelProvider interface.

Maps the normalized types in `devfoundry.providers.types` to/from the
Anthropic Messages API shape (content blocks, tool_use/tool_result blocks,
top-level `system`, forced `tool_choice`). No Anthropic SDK type should
ever leak past this module — callers only ever see the normalized types.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from devfoundry.config import get_anthropic_api_key
from devfoundry.providers.base import ModelProvider, NoToolCallError, ProviderError
from devfoundry.providers.types import (
    ContentBlock,
    GenerateResult,
    Message,
    Role,
    StopReason,
    StreamDone,
    StreamEvent,
    TextBlock,
    TextDelta,
    ToolCallDelta,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    text,
    tool_uses,
)

_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
}


class AnthropicProvider(ModelProvider):
    """ModelProvider backed by the `anthropic` SDK's AsyncAnthropic client.

    `default_model` is deliberately not hardcoded to a guessed model ID —
    pass the model string your account/plan actually has access to, either
    here (used for every call unless overridden) or per-call via the
    `model=` argument on generate/stream/tool_call.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._default_model = default_model
        self._client = client or AsyncAnthropic(api_key=api_key or get_anthropic_api_key())

    def _resolve_model(self, model: str | None) -> str:
        resolved = model or self._default_model
        if not resolved:
            raise ProviderError(
                "No model specified: pass model= per call or default_model= to AnthropicProvider()."
            )
        return resolved

    def _build_kwargs(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None,
        system: str | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        anthropic_messages, system_from_messages = _to_anthropic_messages(messages)
        effective_system = _combine_system(system, system_from_messages)
        kwargs: dict[str, Any] = {
            "model": self._resolve_model(model),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anthropic_messages,
        }
        if effective_system:
            kwargs["system"] = effective_system
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        return kwargs

    async def generate(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> GenerateResult:
        kwargs = self._build_kwargs(
            messages, tools=tools, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
        )
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.AnthropicError as exc:
            raise ProviderError(f"Anthropic API call failed: {exc}") from exc
        return _from_anthropic_message(response)

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamEvent]:
        kwargs = self._build_kwargs(
            messages, tools=tools, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
        )
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            yield ToolCallDelta(
                                index=event.index, id=block.id, name=block.name, partial_json="",
                            )
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield TextDelta(text=delta.text)
                        elif delta.type == "input_json_delta":
                            yield ToolCallDelta(index=event.index, partial_json=delta.partial_json)
                final_message = await stream.get_final_message()
        except anthropic.AnthropicError as exc:
            raise ProviderError(f"Anthropic API call failed: {exc}") from exc
        yield StreamDone(result=_from_anthropic_message(final_message))

    async def tool_call(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        tool_choice: str | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> GenerateResult:
        if not tools:
            raise ProviderError("tool_call() requires at least one tool in `tools`.")
        anthropic_tool_choice = (
            {"type": "tool", "name": tool_choice} if tool_choice else {"type": "any"}
        )
        kwargs = self._build_kwargs(
            messages, tools=tools, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
            tool_choice=anthropic_tool_choice,
        )
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.AnthropicError as exc:
            raise ProviderError(f"Anthropic API call failed: {exc}") from exc
        result = _from_anthropic_message(response)
        if not tool_uses(result.message):
            raise NoToolCallError(
                "Model responded without invoking a tool despite forced tool_choice."
            )
        return result


# --- Mapping helpers ----------------------------------------------------


def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _block_to_anthropic(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    raise ProviderError(f"Unknown content block type: {block!r}")


def _to_anthropic_messages(messages: list[Message]) -> tuple[list[dict[str, Any]], str | None]:
    """Convert normalized Messages to Anthropic's message array, pulling
    any SYSTEM-role messages out into a separate system string (Anthropic
    takes `system` as a top-level param, not a message). Consecutive
    TOOL-role messages are merged into a single Anthropic user turn — the
    API requires all tool_results answering one assistant tool_use turn to
    land in one message."""
    anthropic_messages: list[dict[str, Any]] = []
    system_parts: list[str] = []
    pending_tool_blocks: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        if pending_tool_blocks:
            anthropic_messages.append({"role": "user", "content": list(pending_tool_blocks)})
            pending_tool_blocks.clear()

    for msg in messages:
        if msg.role == Role.SYSTEM:
            flush_tool_results()
            system_parts.append(text(msg))
            continue
        if msg.role == Role.TOOL:
            if isinstance(msg.content, str):
                raise ProviderError("TOOL role message content must be a list of ToolResultBlock.")
            pending_tool_blocks.extend(_block_to_anthropic(b) for b in msg.content)
            continue
        flush_tool_results()
        role = "user" if msg.role == Role.USER else "assistant"
        content = (
            msg.content
            if isinstance(msg.content, str)
            else [_block_to_anthropic(b) for b in msg.content]
        )
        anthropic_messages.append({"role": role, "content": content})
    flush_tool_results()

    system = "\n\n".join(p for p in system_parts if p) or None
    return anthropic_messages, system


def _combine_system(explicit: str | None, from_messages: str | None) -> str | None:
    parts = [p for p in (explicit, from_messages) if p]
    return "\n\n".join(parts) or None


def _from_anthropic_message(response: Any) -> GenerateResult:
    blocks: list[ContentBlock] = []
    for block in response.content:
        if block.type == "text":
            blocks.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            blocks.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))
        # Other block types (e.g. `thinking`) aren't in scope for Phase 1
        # and are dropped rather than mapped, to keep the normalized shape
        # limited to what the interface currently defines.

    content: str | list[ContentBlock]
    if blocks and all(isinstance(b, TextBlock) for b in blocks):
        content = "".join(b.text for b in blocks)
    else:
        content = blocks

    message = Message(role=Role.ASSISTANT, content=content)
    stop_reason = _STOP_REASON_MAP.get(response.stop_reason, StopReason.END_TURN)
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return GenerateResult(
        message=message, stop_reason=stop_reason, usage=usage, model=response.model, raw=response,
    )
