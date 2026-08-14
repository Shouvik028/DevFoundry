# DevFoundry

An AI-native operating layer for software engineering work. A central orchestrator assembles project context and routes tasks to specialized agents — code review, debugging, testing, documentation, and project re-orientation — backed by a reusable skills library and persistent memory.

Full architecture and design rationale: [`docs/spec.md`](docs/spec.md).

> Status: **v0.1 — pre-implementation.** Repo currently holds the scaffold; Phase 1 (`@reviewer` walking skeleton) is in progress.

## Stack

| Layer | Choice |
|---|---|
| Agent core / orchestrator | Python 3.11+ |
| Model abstraction | Custom thin adapter (Anthropic first) |
| API layer | FastAPI (REST + WebSocket) |
| Packaging | uv |
| CLI | Typer + Rich |
| Database | SQLAlchemy + Alembic (SQLite) |
| Dashboard | Vite + React |
| Code search | Tree-sitter (Python, TS/JS) |
| Testing | pytest + Vitest |

## Repo layout

```
devfoundry/
├── src/devfoundry/
│   ├── orchestrator/   # task routing, agent delegation, session state
│   ├── agents/         # agent/persona definitions (@reviewer, @debugger, ...)
│   ├── skills/         # reusable capabilities (git, github, test runner, code search)
│   ├── providers/       # model provider adapters (Anthropic, ...)
│   ├── memory/          # file-based + SQLite memory layer
│   ├── api/              # FastAPI app (REST + WebSocket)
│   └── cli/              # Typer CLI entrypoint
├── dashboard/            # Vite + React web dashboard
├── tests/                # pytest suite
├── docs/
│   └── spec.md           # full project specification
└── pyproject.toml
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
# install dependencies
uv sync --extra dev

# run the API server
uv run uvicorn devfoundry.api.main:app --reload

# run the CLI
uv run devfoundry --help

# run tests
uv run pytest
```

Dashboard (once scaffolded):

```bash
cd dashboard
npm install
npm run dev
```

## License

Not yet licensed — private/personal project for now. Open-source licensing to be decided before any public release.
