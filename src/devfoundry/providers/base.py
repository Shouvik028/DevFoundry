"""Model provider adapter interface.

Every provider (Anthropic first; OpenAI/local via Ollama later) implements
`ModelProvider`. Nothing outside this package should import a provider SDK
directly — the orchestrator and agents talk to this interface only, so
swapping or mixing providers per-agent (spec 3.4) never touches calling
code.

Three methods, deliberately kept separate rather than folded into one
`generate(stream=...)`:

- `generate`   — one-shot, non-streaming completion. May include tool_calls
                 in the returned message if `tools` were offered and the
                 model chose to use one, but plain text is a valid outcome.
- `stream`     — same inputs as `generate`, but yields StreamEvent chunks
                 as they arrive (for CLI/Rich live rendering and the
                 FastAPI WebSocket layer), finishing with a StreamDone that
                 carries the same GenerateResult shape `generate` returns.
- `tool_call`  — like `generate`, but the caller requires a tool
                 invocation, not prose: it forces tool use (all offered
                 tools, or one specific tool via `tool_choice`) and raises
                 `NoToolCallError` if the resulting message carries no
                 ToolUseBlock. This is what the orchestrator uses for
                 structured decisions (e.g. routing) where free text isn't
                 acceptable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from devfoundry.providers.types import (
    GenerateResult,
    Message,
    StreamEvent,
    ToolDefinition,
)


class ProviderError(Exception):
    """Base class for adapter-level failures (auth, rate limit, malformed
    response, etc.) — providers should wrap their SDK's native exceptions
    in this (or a subclass) so callers never need to catch vendor types."""


class NoToolCallError(ProviderError):
    """Raised by tool_call() when the model responded without invoking any
    of the offered tools."""


class ModelProvider(ABC):
    """Provider-agnostic adapter interface. `model` defaults to whatever
    the implementation's config/constructor set, and can be overridden
    per-call — this is what lets config drive model selection per agent
    (e.g. @reviewer on Sonnet, @tester on a cheaper model) while sharing
    one provider instance."""

    name: str

    @abstractmethod
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
        """Non-streaming completion. Returns once the full response is in."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming completion. Async generator; last item is always a
        StreamDone. Callers not interested in incremental output can
        exhaust the iterator and take `StreamDone.result`."""
        ...

    @abstractmethod
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
        """Forced tool-use completion. `tool_choice` names one tool to
        force; omitted, the model must call one of `tools` but picks which.
        Raises NoToolCallError if the result message carries no
        ToolUseBlock. Defaults to temperature=0.0 (distinct from
        generate/stream) since callers use this for structured decisions,
        not creative output."""
        ...
