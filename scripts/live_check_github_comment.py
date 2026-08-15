"""Opt-in live end-to-end check for the review-loop closing skill:
git.diff -> @reviewer -> confirm -> github.pr_comment against a real PR.

Not part of the pytest suite (lives outside tests/) and never runs
automatically. Deliberately requires --repo and --pr-number with no
defaults, so it can't be run by accident against a real PR — and it goes
through the same PermissionGate confirmation flow as the orchestrator
(default_cli_confirm), so you get a y/n prompt naming the exact repo/PR
before anything is actually posted.

    uv run python scripts/live_check_github_comment.py --repo you/your-repo --pr-number 1
    uv run python scripts/live_check_github_comment.py --repo you/your-repo --pr-number 1 --ref HEAD~1..HEAD

Requires ANTHROPIC_API_KEY and GITHUB_TOKEN to be set (.env is loaded
automatically). Costs a small number of real tokens and posts a real PR
comment if you confirm the prompt.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from devfoundry.orchestrator.core import Orchestrator, OrchestratorError
from devfoundry.providers.anthropic import AnthropicProvider
from devfoundry.skills.permissions import PermissionDenied

REPO_ROOT = Path(__file__).resolve().parent.parent


async def main(repo_path: Path, github_repo: str, pr_number: int, ref: str | None, model: str) -> None:
    provider = AnthropicProvider(default_model=model)
    orchestrator = Orchestrator(provider)  # default_cli_confirm: prompts before posting

    try:
        result = await orchestrator.review(
            repo_path,
            ref=ref,
            task_description="Ad-hoc manual review run via live_check_github_comment.py.",
            post_comment=True,
            github_repo=github_repo,
            pr_number=pr_number,
        )
    except OrchestratorError as exc:
        print(f"Nothing to review: {exc}")
        print("Tip: pass --ref HEAD~1..HEAD, or make an uncommitted change first.")
        return
    except PermissionDenied as exc:
        print(f"Declined: {exc}")
        return

    print("--- @reviewer output ---")
    print("summary:", result.review.summary)
    for finding in result.review.findings:
        print(f"- [{finding.severity}] {finding.comment}")

    print(f"\ncomment_posted: {result.comment_posted}")
    print(f"Full pipeline (git.diff -> @reviewer -> confirm -> github.pr_comment) "
          f"completed against {github_repo}#{pr_number}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo-path", type=Path, default=REPO_ROOT, help="Local repo to diff (defaults to this project's root)."
    )
    parser.add_argument(
        "--repo", required=True, help='GitHub repo to post the comment to, "owner/name". No default — required.'
    )
    parser.add_argument(
        "--pr-number", type=int, required=True, help="PR number to comment on. No default — required."
    )
    parser.add_argument(
        "--ref", default=None, help='Commit range, e.g. "HEAD~1..HEAD". Omitted: reviews working tree changes.'
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Model ID to use (defaults to a cheap/fast model to keep this check inexpensive).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.repo_path, args.repo, args.pr_number, args.ref, args.model))