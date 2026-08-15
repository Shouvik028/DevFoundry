"""Orchestrator tests: real git repo (tmp_path-backed, via the git_repo
fixture) for the skill side, mocked provider for the model side — proves
the skill -> agent -> provider assembly line without hitting a real API.

The post_comment tests below also prove the confirmation flow end to end:
github_pr_comment is patched out (no real network calls) so they can
assert both that it's called when approved and, just as importantly, that
it's never called when the confirmation callback declines."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from devfoundry.skills.permissions import PermissionDenied, SkillTier, tier


def make_mock_pr_comment(**kwargs) -> MagicMock:
    """A MagicMock standing in for github_pr_comment, carrying the same
    @tier(SkillTier.MUTATING) marker the real function has — so PermissionGate
    gates it exactly as it would gate the real skill, not by incidental
    Mock equality behavior."""
    mock = MagicMock(**kwargs)
    tier(SkillTier.MUTATING)(mock)
    return mock


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


# --- post_comment / confirmation flow --------------------------------


async def test_post_comment_requires_repo_and_pr_number(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider = make_provider()
    orchestrator = Orchestrator(provider)

    with pytest.raises(OrchestratorError):
        await orchestrator.review(git_repo, post_comment=True)


async def test_post_comment_posts_when_confirmed(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider = make_provider()
    confirm = AsyncMock(return_value=True)
    orchestrator = Orchestrator(provider, confirm=confirm)

    mock_comment = make_mock_pr_comment(return_value={"id": 1})
    with patch("devfoundry.orchestrator.core.github_pr_comment", new=mock_comment):
        result = await orchestrator.review(
            git_repo, post_comment=True, github_repo="acme/widgets", pr_number=7
        )

    assert result.comment_posted is True
    confirm.assert_awaited_once()
    mock_comment.assert_called_once()
    args = mock_comment.call_args.args
    assert args[0] == "acme/widgets"
    assert args[1] == 7
    assert "Looks fine." in args[2]


async def test_post_comment_declined_raises_and_never_calls_skill(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider = make_provider()
    confirm = AsyncMock(return_value=False)
    orchestrator = Orchestrator(provider, confirm=confirm)

    mock_comment = make_mock_pr_comment()
    with (
        patch("devfoundry.orchestrator.core.github_pr_comment", new=mock_comment),
        pytest.raises(PermissionDenied),
    ):
        await orchestrator.review(
            git_repo, post_comment=True, github_repo="acme/widgets", pr_number=7
        )

    confirm.assert_awaited_once()
    mock_comment.assert_not_called()


async def test_review_without_post_comment_never_touches_github(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider = make_provider()
    confirm = AsyncMock(return_value=True)
    orchestrator = Orchestrator(provider, confirm=confirm)

    mock_comment = make_mock_pr_comment()
    with patch("devfoundry.orchestrator.core.github_pr_comment", new=mock_comment):
        result = await orchestrator.review(git_repo)

    assert result.comment_posted is False
    confirm.assert_not_called()
    mock_comment.assert_not_called()
