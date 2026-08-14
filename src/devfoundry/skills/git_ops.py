"""git skills: read-only git operations agents can use as context sources.

Read-only skills need no permission gating (spec 5: read-only skills run
free; mutating/destructive ops require confirmation — that tier system
lands in Stage 2). `git.diff` is the only skill Stage 1 needs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class SkillError(Exception):
    """Raised when a skill can't complete — bad repo path, git not on
    PATH, invalid ref, etc."""


def git_diff(repo_path: str | Path, ref: str | None = None) -> str:
    """Return a unified diff as text.

    - `ref=None`: diffs the working tree (staged + unstaged changes)
      against HEAD — i.e. "what's changed but not yet part of history".
    - `ref="<range>"` (e.g. "HEAD~3..HEAD", "main..feature"): diffs that
      commit range instead.

    Returns an empty string if there's nothing to show (e.g. a clean
    working tree). Raises SkillError if `repo_path` isn't a git repo, git
    isn't available, or `ref` doesn't resolve.
    """
    repo_path = Path(repo_path)
    args = ["git", "-C", str(repo_path), "diff", ref] if ref else ["git", "-C", str(repo_path), "diff", "HEAD"]

    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SkillError("git is not available on PATH.") from exc

    if result.returncode != 0:
        raise SkillError(
            f"git diff failed for {repo_path} (ref={ref!r}): {result.stderr.strip()}"
        )
    return result.stdout
