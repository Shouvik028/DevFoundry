"""DevFoundry CLI entrypoint.

Daily-driver interface: invoke agents interactively, check on background
runs, and manage per-project memory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from devfoundry.config import ConfigError
from devfoundry.orchestrator.core import Orchestrator, OrchestratorError, ReviewTaskResult
from devfoundry.providers.anthropic import AnthropicProvider
from devfoundry.providers.base import ProviderError
from devfoundry.skills.git_ops import SkillError as GitSkillError
from devfoundry.skills.github_ops import SkillError as GithubSkillError
from devfoundry.skills.permissions import PermissionDenied

app = typer.Typer(
    name="devfoundry",
    help="AI-native operating layer for software engineering work.",
    no_args_is_help=True,
)
console = Console()

# Cheap/fast default so `devfoundry review` with no --model is inexpensive
# to run repeatedly; matches the live_check_reviewer.py default. Override
# with --model for a more capable review.
DEFAULT_REVIEW_MODEL = "claude-haiku-4-5-20251001"

_SEVERITY_STYLE = {
    "blocking": "bold red",
    "suggestion": "bold yellow",
    "nit": "dim",
}


@app.command()
def version() -> None:
    """Print the DevFoundry version."""
    console.print("DevFoundry [bold]v0.1.0[/bold] — pre-implementation")


@app.command()
def status() -> None:
    """Check whether the local DevFoundry API server is reachable."""
    console.print("[yellow]Not yet implemented[/yellow] — will ping the FastAPI backend health check.")


@app.command()
def review(
    repo_path: Path = typer.Argument(  # noqa: B008 — standard Typer pattern, not a mutable-default bug
        Path("."),
        exists=True,
        file_okay=False,
        help="Path to the git repo to review. Defaults to the current directory.",
    ),
    ref: str | None = typer.Option(
        None,
        "--ref",
        help='Commit range to review, e.g. "HEAD~1..HEAD". Omitted: reviews working-tree changes.',
    ),
    model: str = typer.Option(
        DEFAULT_REVIEW_MODEL,
        "--model",
        help="Anthropic model ID to run @reviewer on.",
    ),
    post_comment: bool = typer.Option(
        False,
        "--post-comment",
        help="Post the review as a GitHub PR comment. Requires --github-repo and --pr-number.",
    ),
    github_repo: str | None = typer.Option(
        None,
        "--github-repo",
        help='GitHub repo to post to, "owner/name". Required with --post-comment.',
    ),
    pr_number: int | None = typer.Option(
        None,
        "--pr-number",
        help="PR number to post the comment to. Required with --post-comment.",
    ),
) -> None:
    """Run @reviewer over a diff and print its findings.

    Reviews the working-tree diff in `repo_path` by default (or the range
    named by --ref). Pass --post-comment along with --github-repo and
    --pr-number to also post the findings as a PR comment — this asks for
    confirmation first (see PermissionGate) since it's a mutating action.
    """
    if post_comment and (not github_repo or pr_number is None):
        console.print("[red]--post-comment requires both --github-repo and --pr-number.[/red]")
        raise typer.Exit(code=1)

    try:
        provider = AnthropicProvider(default_model=model)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    orchestrator = Orchestrator(provider)

    try:
        result = asyncio.run(
            orchestrator.review(
                repo_path,
                ref=ref,
                post_comment=post_comment,
                github_repo=github_repo,
                pr_number=pr_number,
            )
        )
    except OrchestratorError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1) from exc
    except PermissionDenied as exc:
        console.print(f"[yellow]Declined — nothing was posted.[/yellow] ({exc})")
        raise typer.Exit(code=1) from exc
    except (GitSkillError, GithubSkillError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _render_review(result)


def _render_review(result: ReviewTaskResult) -> None:
    review_result = result.review
    console.print(Panel(review_result.summary or "(no summary)", title="@reviewer", border_style="cyan"))

    if not review_result.findings:
        console.print("[green]No findings.[/green]")
    else:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Severity")
        table.add_column("Location")
        table.add_column("Comment")
        for finding in review_result.findings:
            style = _SEVERITY_STYLE.get(finding.severity, "white")
            table.add_row(
                f"[{style}]{finding.severity}[/{style}]",
                finding.line_ref or "-",
                finding.comment,
            )
        console.print(table)

    if result.comment_posted:
        console.print("[green]Posted as a PR comment.[/green]")


if __name__ == "__main__":
    app()