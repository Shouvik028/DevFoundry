"""Opt-in live end-to-end check for the @reviewer walking skeleton —
skill -> agent -> provider -> result against this actual repo and a real
Anthropic call.

Not part of the pytest suite (lives outside tests/) and never runs
automatically. Run it yourself, deliberately:

    uv run python scripts/live_check_reviewer.py
    uv run python scripts/live_check_reviewer.py --ref HEAD~1..HEAD
    uv run python scripts/live_check_reviewer.py --model claude-sonnet-4-5

With no --ref and a clean working tree there's nothing to review — either
make an uncommitted edit first, or pass --ref to review a commit range.

Requires ANTHROPIC_API_KEY to be set (.env is loaded automatically).
Costs a small number of real tokens each run.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from devfoundry.orchestrator.core import Orchestrator, OrchestratorError
from devfoundry.providers.anthropic import AnthropicProvider

REPO_ROOT = Path(__file__).resolve().parent.parent


async def main(repo_path: Path, ref: str | None, model: str) -> None:
    provider = AnthropicProvider(default_model=model)
    orchestrator = Orchestrator(provider)

    try:
        result = await orchestrator.review(
            repo_path, ref=ref, task_description="Ad-hoc manual review run via live_check_reviewer.py."
        )
    except OrchestratorError as exc:
        print(f"Nothing to review: {exc}")
        print("Tip: pass --ref HEAD~1..HEAD, or make an uncommitted change first.")
        return

    print("--- diff reviewed ---")
    preview = result.diff if len(result.diff) <= 2000 else result.diff[:2000] + "\n... (truncated)"
    print(preview)

    print("\n--- @reviewer output ---")
    print("summary:", result.review.summary)
    if not result.review.findings:
        print("(no findings)")
    for finding in result.review.findings:
        location = f" ({finding.line_ref})" if finding.line_ref else ""
        print(f"- [{finding.severity}]{location} {finding.comment}")

    print("\nFull pipeline (git.diff -> @reviewer -> AnthropicProvider) completed against the live API.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-path", type=Path, default=REPO_ROOT, help="Repo to review (defaults to this project's root)."
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
    asyncio.run(main(args.repo_path, args.ref, args.model))
