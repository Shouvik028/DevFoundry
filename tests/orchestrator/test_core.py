"""Orchestrator tests: real git repo (tmp_path-backed, via the git_repo
fixture) for the skill side, mocked provider for the model side — proves
the skill -> agent -> provider assembly line without hitting a real API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from devfoundry.orchestrator.core import Orchestrator, OrchestratorError
from devfoundry.providers.base import ModelProvider
from devfoundry.providers.types import (
    GenerateResult,
    Message,
    Role,
    StopReason,
    ToolUseBlock,
    Usage,
)


def make_provider() -> MagicMock:
    provider = MagicMock(spec=ModelProvider)
    provider.tool_call = AsyncMock(
        return_value=GenerateResult(
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    ToolUseBlock(
                        id="call_1",
                        name="submit_review",
                        input={"summary": "Looks fine.", "findings": []},
                    )
                ],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=100, output_tokens=50),
            model="claude-test-model",
        )
    )
    return provider


async def test_review_assembles_skill_agent_and_provider(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider = make_provider()
    orchestrator = Orchestrator(provider)

    result = await orchestrator.review(git_repo, task_description="Review my change")

    assert "hello, changed" in result.diff
    assert result.review.summary == "Looks fine."
    provider.tool_call.assert_awaited_once()


async def test_review_passes_ref_through(git_repo: Path):
    provider = make_provider()
    orchestrator = Orchestrator(provider)

    result = await orchestrator.review(git_repo, ref="HEAD~1..HEAD")

    assert "hello again" in result.diff
    provider.tool_call.assert_awaited_once()


async def test_review_raises_when_nothing_to_review(git_repo: Path):
    provider = make_provider()
    orchestrator = Orchestrator(provider)

    with pytest.raises(OrchestratorError):
        await orchestrator.review(git_repo)

    provider.tool_call.assert_not_called()
