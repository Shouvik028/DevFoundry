"""Orchestrator core — single entry point for task requests.

Stage 1: only one agent exists (@reviewer), so there's no routing or
classification yet (spec 3.1's "classify -> route" logic lands once a
second agent exists in Stage 2/Phase 2). This is deliberately just the
assembly line: skill -> agent -> provider -> result, to prove the loop
before adding orchestration logic on top of it.

Stage 2: closes the review loop with github.pr_comment. Every skill call —
read-only or mutating — is routed through self.permissions (a
PermissionGate) rather than called directly, so there's one audit trail
and one enforcement point for confirmation (spec 3.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devfoundry.agents.reviewer import ReviewerAgent, ReviewFinding, ReviewResult
from devfoundry.providers.base import ModelProvider
from devfoundry.skills.git_ops import git_diff
from devfoundry.skills.github_ops import github_pr_comment
from devfoundry.skills.permissions import ConfirmCallback, PermissionGate


class OrchestratorError(Exception):
    """Raised when a task can't be assembled — e.g. nothing to review, or
    post_comment=True without enough info to know where to post."""


@dataclass
class ReviewTaskResult:
    diff: str
    review: ReviewResult
    comment_posted: bool = False


class Orchestrator:
    """Holds a provider and the (currently one) agent roster. Agents don't
    call skills directly — the orchestrator gathers context via skills and
    hands it to the agent — which is what keeps a single audit trail now
    that permission tiers exist (spec 3.1)."""

    def __init__(self, provider: ModelProvider, *, confirm: ConfirmCallback | None = None) -> None:
        self.provider = provider
        self.reviewer = ReviewerAgent()
        self.permissions = PermissionGate(confirm)

    async def review(
        self,
        repo_path: str | Path,
        *,
        ref: str | None = None,
        task_description: str = "",
        model: str | None = None,
        post_comment: bool = False,
        github_repo: str | None = None,
        pr_number: int | None = None,
    ) -> ReviewTaskResult:
        """Review a diff from `repo_path`. `ref` selects a commit range
        (see skills.git_ops.git_diff); omitted, reviews working tree
        changes. Raises OrchestratorError if there's nothing to review.

        If `post_comment=True`, also posts the review as a PR comment via
        github_pr_comment — `github_repo` ("owner/name") and `pr_number`
        are then required. Posting goes through PermissionGate first
        (github_pr_comment is SkillTier.MUTATING), so it only happens if
        the confirmation callback approves; a decline raises
        PermissionDenied and no comment is posted.
        """
        diff = await self.permissions.run(
            git_diff,
            repo_path,
            ref=ref,
            summary=f"Read the diff for {repo_path} (ref={ref!r}).",
            details={"repo_path": str(repo_path), "ref": ref},
        )
        if not diff.strip():
            raise OrchestratorError(
                f"No changes to review in {repo_path} (ref={ref!r})."
            )
        review = await self.reviewer.review(
            self.provider, diff, task_description=task_description, model=model
        )
        result = ReviewTaskResult(diff=diff, review=review)

        if post_comment:
            if not github_repo or pr_number is None:
                raise OrchestratorError(
                    "post_comment=True requires both github_repo and pr_number."
                )
            comment_body = _format_review_comment(review)
            await self.permissions.run(
                github_pr_comment,
                github_repo,
                pr_number,
                comment_body,
                summary=f"Post @reviewer's findings as a PR comment on {github_repo}#{pr_number}.",
                details={
                    "repo": github_repo,
                    "pr_number": pr_number,
                    "preview": comment_body[:200],
                },
            )
            result.comment_posted = True

        return result


def _format_review_comment(review: ReviewResult) -> str:
    lines = ["**@reviewer**", "", review.summary]
    if review.findings:
        lines.append("")
        lines.extend(_format_finding(f) for f in review.findings)
    return "\n".join(lines)


def _format_finding(finding: ReviewFinding) -> str:
    location = f" ({finding.line_ref})" if finding.line_ref else ""
    return f"- **[{finding.severity}]**{location} {finding.comment}"
