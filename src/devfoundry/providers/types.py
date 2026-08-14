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


# --- Content blocks -----------------------------------------------------
#
# A Message's content is either a plain string (the common case: a user
# prompt, a system instruction, plain assistant prose) or a list of these
# blocks, when the turn needs to carry structure — an assistant proposing
# one or more tool calls, or a reply carrying one or more tool results.
# This mirrors Anthropic's native content-block shape directly; an
# OpenAI-style adapter would map ToolUseBlock -> its `tool_calls` array and
# ToolResultBlock -> a role="tool" message with matching tool_call_id.


@dataclass
class TextBlock:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ToolUseBlock:
    """A model-requested invocation of a tool. The orchestrator executes
    it (never the agent directly) and feeds the outcome back as a
    ToolResultBlock with matching `id`."""

    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class Message:
    """One turn in the conversation.

    - USER / SYSTEM: usually a plain string; a list is only needed if the
      turn is carrying tool results back (role=TOOL messages use a list of
      ToolResultBlock).
    - ASSISTANT: a string for plain prose, or a list mixing TextBlock and
      ToolUseBlock when the model responded with (or alongside) tool
      invocations.
    - TOOL: a list of one or more ToolResultBlock, each keyed by
      tool_use_id back to the ToolUseBlock it answers.
    """

    role: Role
    content: str | list[ContentBlock]


def tool_uses(message: Message) -> list[ToolUseBlock]:
    """Extract any ToolUseBlock entries from a message's content. Returns
    an empty list for plain-string content or content with no tool uses."""
    if isinstance(message.content, str):
        return []
    return [block for block in message.content if isinstance(block, ToolUseBlock)]


def text(message: Message) -> str:
    """Concatenate a message's text content, ignoring tool blocks. Returns
    the string directly for plain-string content."""
    if isinstance(message.content, str):
        return message.content
    return "".join(block.text for block in message.content if isinstance(block, TextBlock))


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
