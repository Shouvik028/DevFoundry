"""Mocked tests for ReviewerAgent — the ModelProvider is faked (MagicMock
spec'd to the interface, tool_call as AsyncMock), same pattern used for
the Anthropic SDK client in tests/providers/test_anthropic.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from devfoundry.agents.reviewer import SUBMIT_REVIEW_TOOL, ReviewerAgent, ReviewError
from devfoundry.providers.base import ModelProvider
from devfoundry.providers.types import (
    GenerateResult,
    Message,
    Role,
    StopReason,
    ToolUseBlock,
    Usage,
)

SAMPLE_DIFF = """\
diff --git a/hello.py b/hello.py
index e69de29..4b825dc 100644
--- a/hello.py
+++ b/hello.py
@@ -1 +1 @@
-print('hello')
+print('hello again')
"""


def make_provider(tool_input: dict) -> MagicMock:
    provider = MagicMock(spec=ModelProvider)
    provider.tool_call = AsyncMock(
        return_value=GenerateResult(
            message=Message(
                role=Role.ASSISTANT,
                content=[ToolUseBlock(id="call_1", name="submit_review", input=tool_input)],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=100, output_tokens=50),
            model="claude-test-model",
        )
    )
    return provider


async def test_review_returns_structured_result():
    provider = make_provider(
        {
            "summary": "Minor rewording, looks fine.",
            "findings": [
                {"severity": "nit", "comment": "Consider a more descriptive message.", "line_ref": "hello.py"}
            ],
        }
    )
    agent = ReviewerAgent()

    result = await agent.review(provider, SAMPLE_DIFF, task_description="Review this PR")

    assert result.summary == "Minor rewording, looks fine."
    assert len(result.findings) == 1
    assert result.findings[0].severity == "nit"
    assert result.findings[0].line_ref == "hello.py"


async def test_review_calls_provider_with_forced_submit_review_tool():
    provider = make_provider({"summary": "ok", "findings": []})
    agent = ReviewerAgent()

    await agent.review(provider, SAMPLE_DIFF, model="claude-test-model")

    provider.tool_call.assert_awaited_once()
    _, kwargs = provider.tool_call.call_args
    assert kwargs["tools"] == [SUBMIT_REVIEW_TOOL]
    assert kwargs["tool_choice"] == "submit_review"
    assert kwargs["system"] == agent.system_prompt
    assert kwargs["model"] == "claude-test-model"

    messages = provider.tool_call.call_args.args[0]
    assert SAMPLE_DIFF in messages[0].content


async def test_review_skips_provider_call_for_empty_diff():
    provider = make_provider({"summary": "unused", "findings": []})
    agent = ReviewerAgent()

    result = await agent.review(provider, "   ")

    assert result.summary == "No changes to review."
    assert result.findings == []
    provider.tool_call.assert_not_called()


async def test_review_raises_on_malformed_tool_input():
    provider = make_provider({"summary": "ok", "findings": [{"severity": "nit"}]})  # missing "comment"
    agent = ReviewerAgent()

    with pytest.raises(ReviewError):
        await agent.review(provider, SAMPLE_DIFF)
