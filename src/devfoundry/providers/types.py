"""Provider-agnostic data types for the model adapter interface.

These shapes are the contract every provider (Anthropic now, OpenAI/local
later) normalizes into and out of. Keep them free of any single vendor's
SDK types so swapping providers never touches calling code — see
ModelProvider in base.py for the interface these types support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(str, Enum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"


@dataclass
class ToolDefinition:
    """Describes one callable tool/skill offered to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for the tool's arguments


@dataclass
class ToolCall:
    """A model-requested invocation of a tool. The orchestrator executes
    it (never the agent directly) and feeds the result back as a Message
    with role=TOOL and matching tool_call_id."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Message:
    """One turn in the conversation. Shape is intentionally generic so it
    maps cleanly onto both content-block APIs (Anthropic) and
    tool_calls-array APIs (OpenAI-style):

    - USER / SYSTEM: `content` set, everything else None.
    - ASSISTANT: `content` (may be empty string) and/or `tool_calls` set,
      when the model responded with one or more tool invocations.
    - TOOL: `content` is the stringified result, `tool_call_id` links it
      back to the ToolCall it answers, `is_error` flags a failed call.
    """

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class GenerateResult:
    """Return shape for both generate() and tool_call() — and what
    stream() assembles into once a stream finishes."""

    message: Message
    stop_reason: StopReason
    usage: Usage
    model: str
    raw: Any = field(default=None, repr=False, compare=False)


# --- Streaming events -------------------------------------------------

@dataclass
class TextDelta:
    """Incremental assistant text."""

    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass
class ToolCallDelta:
    """Incremental tool-call assembly. `partial_json` fragments concatenate
    into the full JSON string for the tool's input; `name`/`id` are set
    once, on the first delta for a given `index`."""

    index: int
    partial_json: str
    id: str | None = None
    name: str | None = None
    type: Literal["tool_call_delta"] = "tool_call_delta"


@dataclass
class StreamDone:
    """Final event of every stream — carries the fully assembled result,
    same shape generate() would have returned for the same call."""

    result: GenerateResult
    type: Literal["stream_done"] = "stream_done"


StreamEvent = TextDelta | ToolCallDelta | StreamDone
