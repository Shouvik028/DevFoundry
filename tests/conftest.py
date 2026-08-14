"""Shared fixtures for local, real (non-mocked) git repos used by skill and
orchestrator tests — cheap and fast, so no reason to fake git itself."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real git repo with two commits and a clean working tree.
    Tests that want working-tree changes should modify a file afterward."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)

    (repo / "hello.py").write_text("print('hello')\n")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo)

    (repo / "hello.py").write_text("print('hello again')\n")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "second commit"], cwd=repo)

    return repo
