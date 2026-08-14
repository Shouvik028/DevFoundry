"""FastAPI entrypoint for the DevFoundry orchestrator API.

Serves both the CLI and the web dashboard over REST + WebSocket.
Phase 1: minimal health check + placeholder routing; orchestrator wiring lands next.
"""

from fastapi import FastAPI

app = FastAPI(
    title="DevFoundry",
    description="AI-native operating layer for software engineering work.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# TODO(Phase 1): mount orchestrator routes, WebSocket streaming endpoint for
# agent output, and the @reviewer task route as the first end-to-end flow.
