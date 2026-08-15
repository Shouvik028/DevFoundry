"""Mocked tests for github_ops. No real network calls — httpx.post is
patched out entirely. See scripts/live_check_github_comment.py for the
opt-in real-API smoke check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from devfoundry.skills.github_ops import SkillError, github_pr_comment
from devfoundry.skills.permissions import SkillTier, get_tier


def make_response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    return response


def test_github_pr_comment_is_mutating_tier():
    assert get_tier(github_pr_comment) == SkillTier.MUTATING


def test_github_pr_comment_success():
    response = make_response(201, {"id": 123, "body": "nice work"})
    with patch("devfoundry.skills.github_ops.httpx.post", return_value=response) as mock_post:
        result = github_pr_comment("acme/widgets", 42, "nice work", token="ghp_test")

    assert result == {"id": 123, "body": "nice work"}
    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert url == "https://api.github.com/repos/acme/widgets/issues/42/comments"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["json"] == {"body": "nice work"}
    assert kwargs["headers"]["Authorization"] == "Bearer ghp_test"


def test_github_pr_comment_uses_config_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
    response = make_response(201, {"id": 1})
    with patch("devfoundry.skills.github_ops.httpx.post", return_value=response) as mock_post:
        github_pr_comment("acme/widgets", 42, "hello")

    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer ghp_from_env"


def test_github_pr_comment_raises_on_empty_body():
    with pytest.raises(SkillError):
        github_pr_comment("acme/widgets", 42, "   ", token="ghp_test")


def test_github_pr_comment_raises_on_api_error_status():
    response = make_response(404, text='{"message": "Not Found"}')
    with (
        patch("devfoundry.skills.github_ops.httpx.post", return_value=response),
        pytest.raises(SkillError, match="404"),
    ):
        github_pr_comment("acme/widgets", 42, "hello", token="bad-token")


def test_github_pr_comment_raises_on_network_error():
    with (
        patch(
            "devfoundry.skills.github_ops.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ),
        pytest.raises(SkillError),
    ):
        github_pr_comment("acme/widgets", 42, "hello", token="ghp_test")