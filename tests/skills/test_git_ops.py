from __future__ import annotations

from pathlib import Path

import pytest

from devfoundry.skills.git_ops import SkillError, git_diff


def test_git_diff_no_working_tree_changes(git_repo: Path):
    assert git_diff(git_repo) == ""


def test_git_diff_working_tree_changes(git_repo: Path):
    (git_repo / "hello.py").write_text("print('hello, uncommitted')\n")

    diff = git_diff(git_repo)

    assert "hello, uncommitted" in diff
    assert diff.startswith("diff --git")


def test_git_diff_commit_range(git_repo: Path):
    diff = git_diff(git_repo, ref="HEAD~1..HEAD")

    assert "hello again" in diff


def test_git_diff_raises_for_non_repo(tmp_path: Path):
    with pytest.raises(SkillError):
        git_diff(tmp_path)


def test_git_diff_raises_for_bad_ref(git_repo: Path):
    with pytest.raises(SkillError):
        git_diff(git_repo, ref="not-a-real-ref..HEAD")
