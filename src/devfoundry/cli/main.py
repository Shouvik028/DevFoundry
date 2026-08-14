"""DevFoundry CLI entrypoint.

Daily-driver interface: invoke agents interactively, check on background
runs, and manage per-project memory.
"""

import typer
from rich.console import Console

app = typer.Typer(
    name="devfoundry",
    help="AI-native operating layer for software engineering work.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Print the DevFoundry version."""
    console.print("DevFoundry [bold]v0.1.0[/bold] — pre-implementation")


@app.command()
def status() -> None:
    """Check whether the local DevFoundry API server is reachable."""
    console.print("[yellow]Not yet implemented[/yellow] — will ping the FastAPI backend health check.")


# TODO(Phase 1): `devfoundry review <pr>` as the first real command, wired to
# the orchestrator via the FastAPI backend (REST call + WebSocket stream for
# live output).


if __name__ == "__main__":
    app()
