"""Orchestrator core — single entry point for task requests.

Stage 1: only one agent exists (@reviewer), so there's no routing or
classification yet (spec 3.1's "classify -> route" logic lands once a
second agent exists in Stage 2/Phase 2). This is deliberately just the
assembly line: skill -> agent -> provider -> result, to prove the loop
before adding orchestration logic on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devfoundry.agents.reviewer import ReviewerAgent, ReviewResult
from devfoundry.providers.base import ModelProvider
from devfoundry.skills.git_ops import git_diff


class OrchestratorError(Exception):
    """Raised when a task can't be assembled — e.g. nothing to review."""


@dataclass
class ReviewTaskResult:
    diff: str
    review: ReviewResult


class Orchestrator:
    """Holds a provider and the (currently one) agent roster. Agents don't
    call skills directly — the orchestrator gathers context via skills and
    hands it to the agent — which is what keeps a single audit trail once
    permission tiers land in Stage 2 (spec 3.1)."""

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider
        self.reviewer = ReviewerAgent()

    async def review(
        self,
        repo_path: str | Path,
        *,
        ref: str | None = None,
        task_description: str = "",
        model: str | None = None,
    ) -> ReviewTaskResult:
        """Review a diff from `repo_path`. `ref` selects a commit range
        (see skills.git_ops.git_diff); omitted, reviews working tree
        changes. Raises OrchestratorError if there's nothing to review."""
        diff = git_diff(repo_path, ref=ref)
        if not diff.strip():
            raise OrchestratorError(
                f"No changes to review in {repo_path} (ref={ref!r})."
            )
        review = await self.reviewer.review(
            self.provider, diff, task_description=task_description, model=model
        )
        return ReviewTaskResult(diff=diff, review=review)
