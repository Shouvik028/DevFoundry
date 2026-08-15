"""CLI tests for `devfoundry review` — proves argument wiring, output
rendering, the missing-API-key error path, and (importantly) that
PermissionGate's confirmation prompt actually reads through Typer's
CliRunner-supplied stdin rather than silently hanging or reading the real
terminal. The provider is mocked (same pattern as the orchestrator tests
in tests/orchestrator/test_core.py); real API calls are what the
live_check scripts remain for."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from devfoundry.cli.main import app
from devfoundry.providers.types import (
    GenerateResult,
    Message,
    Role,
    StopReason,
    ToolUseBlock,
    Usage,
)
from devfoundry.skills.permissions import SkillTier, tier

runner = CliRunner()


def make_provider_cls(summary: str = "Looks fine.", findings: list[dict] | None = None) -> MagicMock:
    """A MagicMock standing in for the AnthropicProvider *class*: calling
    it, as cli.main does (`AnthropicProvider(default_model=model)`),
    returns a provider double with a mocked async tool_call — so no real
    API key or network call is needed to exercise the command."""
    provider = MagicMock()
    provider.tool_call = AsyncMock(
        return_value=GenerateResult(
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    ToolUseBlock(
                        id="call_1",
                        name="submit_review",
                        input={"summary": summary, "findings": findings or []},
                    )
                ],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=100, output_tokens=50),
            model="claude-test-model",
        )
    )
    return MagicMock(return_value=provider)


def make_mock_pr_comment(**kwargs) -> MagicMock:
    """Mirrors tests/orchestrator/test_core.py's helper: a MagicMock
    carrying the same @tier(SkillTier.MUTATING) marker as the real
    github_pr_comment, so PermissionGate gates it exactly as it would the
    real skill."""
    mock = MagicMock(**kwargs)
    tier(SkillTier.MUTATING)(mock)
    return mock


def test_review_renders_summary_and_findings(git_repo: Path) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    findings = [{"severity": "blocking", "comment": "Off by one.", "line_ref": "hello.py:1"}]
    provider_cls = make_provider_cls(summary="Needs a fix.", findings=findings)

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo)])

    assert result.exit_code == 0, result.output
    assert "Needs a fix." in result.output
    assert "blocking" in result.output
    assert "Off by one." in result.output
    assert "hello.py:1" in result.output
    provider_cls.return_value.tool_call.assert_awaited_once()


def test_review_no_findings_renders_clean_message(git_repo: Path) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider_cls = make_provider_cls(summary="Looks fine.", findings=[])

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo)])

    assert result.exit_code == 0, result.output
    assert "No findings." in result.output


def test_review_passes_ref_through(git_repo: Path) -> None:
    provider_cls = make_provider_cls()

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo), "--ref", "HEAD~1..HEAD"])

    assert result.exit_code == 0, result.output
    provider_cls.return_value.tool_call.assert_awaited_once()
    prompt = provider_cls.return_value.tool_call.call_args.args[0][0].content
    assert "hello again" in prompt


def test_review_model_option_passed_to_provider(git_repo: Path) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider_cls = make_provider_cls()

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo), "--model", "claude-sonnet-test"])

    assert result.exit_code == 0, result.output
    provider_cls.assert_called_once_with(default_model="claude-sonnet-test")


def test_review_defaults_to_cwd(git_repo: Path, monkeypatch) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    monkeypatch.chdir(git_repo)
    provider_cls = make_provider_cls()

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review"])

    assert result.exit_code == 0, result.output
    provider_cls.return_value.tool_call.assert_awaited_once()


def test_review_nothing_to_review(git_repo: Path) -> None:
    provider_cls = make_provider_cls()

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo)])

    assert result.exit_code == 1
    assert "No changes to review" in result.output
    provider_cls.return_value.tool_call.assert_not_called()


def test_review_post_comment_requires_repo_and_pr_number(git_repo: Path) -> None:
    provider_cls = make_provider_cls()

    with patch("devfoundry.cli.main.AnthropicProvider", provider_cls):
        result = runner.invoke(app, ["review", str(git_repo), "--post-comment"])

    assert result.exit_code == 1
    assert "requires both --github-repo and --pr-number" in result.output
    provider_cls.assert_not_called()


def test_review_missing_api_key(git_repo: Path, monkeypatch) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["review", str(git_repo)])

    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_review_post_comment_confirmed_via_stdin(git_repo: Path) -> None:
    """Proves the confirmation prompt (PermissionGate's default_cli_confirm,
    which reads via asyncio.to_thread(input, ...) from inside the CLI's own
    asyncio.run() call) actually reads through Typer's CliRunner-supplied
    stdin end to end, rather than assuming it inherits cleanly."""
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider_cls = make_provider_cls()
    mock_comment = make_mock_pr_comment(return_value={"id": 1})

    with (
        patch("devfoundry.cli.main.AnthropicProvider", provider_cls),
        patch("devfoundry.orchestrator.core.github_pr_comment", new=mock_comment),
    ):
        result = runner.invoke(
            app,
            ["review", str(git_repo), "--post-comment", "--github-repo", "acme/widgets", "--pr-number", "7"],
            input="y\n",
        )

    assert result.exit_code == 0, result.output
    assert "Posted as a PR comment." in result.output
    mock_comment.assert_called_once()


def test_review_post_comment_declined_via_stdin(git_repo: Path) -> None:
    (git_repo / "hello.py").write_text("print('hello, changed')\n")
    provider_cls = make_provider_cls()
    mock_comment = make_mock_pr_comment()

    with (
        patch("devfoundry.cli.main.AnthropicProvider", provider_cls),
        patch("devfoundry.orchestrator.core.github_pr_comment", new=mock_comment),
    ):
        result = runner.invoke(
            app,
            ["review", str(git_repo), "--post-comment", "--github-repo", "acme/widgets", "--pr-number", "7"],
            input="n\n",
        )

    assert result.exit_code == 1
    assert "Declined" in result.output
    mock_comment.assert_not_called()
