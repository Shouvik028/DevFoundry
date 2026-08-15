"""GitHub skills: operations against the GitHub REST API.

Unlike git_ops (local git, read-only for now), `github_pr_comment` mutates
a remote resource other people will see — declared SkillTier.MUTATING so
PermissionGate confirms before the orchestrator calls it (spec 3.1/5).
"""

from __future__ import annotations

from typing import Any

import httpx

from devfoundry.config import get_github_token
from devfoundry.skills.permissions import SkillTier, tier

GITHUB_API_BASE = "https://api.github.com"


class SkillError(Exception):
    """Raised when a GitHub skill can't complete — bad token, PR not
    found, rate limited, network failure, etc. Mirrors git_ops.SkillError:
    callers never need to catch httpx's exception types directly."""


@tier(SkillTier.MUTATING)
def github_pr_comment(
    repo: str,
    pr_number: int,
    body: str,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Post a comment on a pull request. `repo` is "owner/name"; GitHub
    treats PRs as issues for commenting purposes, so this hits the
    issues/comments endpoint. Returns the created comment's JSON.

    Raises SkillError on any API failure (bad/missing token, PR not found,
    rate limited, network error) or if `body` is empty.
    """
    if not body.strip():
        raise SkillError("Comment body must not be empty.")

    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token or get_github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = httpx.post(url, headers=headers, json={"body": body}, timeout=30.0)
    except httpx.HTTPError as exc:
        raise SkillError(f"GitHub API request failed for {repo}#{pr_number}: {exc}") from exc

    if response.status_code >= 400:
        raise SkillError(
            f"GitHub API returned {response.status_code} for {repo}#{pr_number}: "
            f"{response.text.strip()}"
        )
    return response.json()
