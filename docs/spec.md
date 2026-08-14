# DevFoundry — Project Specification (v0.1)

## 1. Vision

DevFoundry is a personal, AI-native operating layer for software engineering work. It's not a chatbot bolted onto an editor — it's a standalone system with persistent memory, a roster of specialized agents/personas, a library of reusable skills, and an orchestrator that routes work to the right agent. It runs where you already work (terminal) and gives you visibility where you want it (web dashboard).

Design principle: **every core workflow (review, debug, test, document, re-orient) is fundamentally a context-assembly problem.** The system's main value-add is gathering the right context (code, git history, prior decisions, related PRs) fast and handing it to the right specialist, not any single clever prompt.

Built to be genuinely owned — model-agnostic, self-hosted, open-sourceable later without an untangling project.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Interfaces                            │
│   CLI (Typer/Rich TUI)         Web Dashboard (Vite/React)     │
└───────────────┬─────────────────────────────┬─────────────────┘
                │                             │
                └──────────────┬──────────────┘
                               │  (local REST/WebSocket API)
                    ┌──────────▼──────────┐
                    │   Orchestrator       │  routes tasks, holds
                    │   (Python core)      │  conversation/task state
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
   ┌─────▼─────┐        ┌─────▼─────┐        ┌─────▼─────┐
   │  Agents/   │        │  Skills    │        │  Model     │
   │  Personas  │◄──────►│  Library   │        │  Provider  │
   │ (reviewer, │  use   │ (git ops,  │        │  Adapter   │
   │  debugger, │        │  test run, │        │ (Claude /  │
   │  tester,   │        │  code      │        │  GPT /     │
   │  docs,     │        │  search,   │        │  local)    │
   │  context-  │        │  file ops) │        └───────────┘
   │  broker)   │        └───────────┘
   └───────────┘
         │
   ┌─────▼──────────────────────────────┐
   │  Memory Layer                       │
   │  • Files (md/JSON, git-tracked)     │  → project specs, agent
   │  •  SQLite (per-project db)         │    definitions, decisions
   └─────────────────────────────────────┘  → session history, run
                                              logs, embeddings/index
```

---

## 3. Core Components

### 3.1 Orchestrator (Python)
- Single entry point for all requests (from CLI or web API).
- Classifies incoming task → routes to a specialist agent, or handles directly for simple asks.
- Maintains task/session state; supports both "fire and forget" (background) and "interactive" (chat) modes per your earlier answer.
- Holds the tool-execution loop: agents don't call tools directly, they request actions through the orchestrator, which executes skills and returns results. This keeps a single audit trail and a single place to enforce permissions/sandboxing.

### 3.2 Agents / Personas
Each is a config (system prompt + tool allowlist + memory scope), not necessarily separate code:

| Agent | Job | Primary skills used |
|---|---|---|
| `@reviewer` | PR/diff review, style & correctness feedback | git diff, GitHub API, static analysis |
| `@debugger` | Root-cause a bug from a stack trace/repro | log search, git blame/bisect, test runner |
| `@tester` | Write/extend tests for a module or PR | code search, test runner, coverage tool |
| `@docs` | Generate/update docs, capture decisions | code search, file ops, doc-diff |
| `@context-broker` | Re-orient you when switching repos/projects | memory query, git log, README/spec digest |
| `@orchestrator` (default) | Decide who handles a task; multi-agent handoff | all (delegates) |

You can `@mention` an agent directly, or let the orchestrator pick.

### 3.3 Skills Library
Reusable, composable capabilities every agent can call — analogous to Claude Code's skills concept:
- `git.diff`, `git.blame`, `git.bisect`, `git.log`
- `github.pr_list`, `github.pr_comment`, `github.issue_search`
- `test.run`, `test.coverage`
- `code.search` (ripgrep/AST-aware), `code.read`, `code.edit`
- `memory.query`, `memory.write` (writes to file or DB depending on type)

Skills are the thing you'll keep extending over time — each is a small, testable, single-purpose module.

### 3.4 Model Provider Layer
- Custom thin abstraction interface (`generate`, `stream`, `tool_call`) implemented per-provider (Anthropic first, OpenAI/local via Ollama later).
- Config-driven model selection per agent (e.g., `@reviewer` on Claude Sonnet, `@tester` on a cheaper/faster model) — matters once you're paying for API calls across many agents.
- Built in-house rather than via LiteLLM or similar, to keep tool-calling reliability fully under your control — see Section 5 for the finalized stack.

### 3.5 Memory Layer
- **Files** (git-tracked, per-project): project spec, architecture notes, agent/skill configs, decisions log — human-readable, diffable, reviewable in PRs.
- **SQLite** (per-project, gitignored): session/task history, run logs, embeddings/index for code search, anything high-volume or non-human-readable.

### 3.6 Interfaces
- **CLI**: primary daily driver. Typer for commands, Rich for TUI output (streaming agent responses, diff rendering).
- **Web dashboard**: Vite + React SPA, talks to the same local FastAPI backend the CLI uses. Shows history, active/background agent runs, memory browser. Not required for daily use — it's for visibility and later, shareability.

---

## 4. Phasing

**Phase 1 — MVP (single agent, prove the loop)**
- Orchestrator + model provider abstraction (Claude only, but through the abstraction layer)
- One agent fully working end-to-end: `@reviewer` (highest signal, easiest to validate)
- Skills: `git.diff`, `github.pr_comment`, `code.search`
- File-based memory only (skip SQLite initially)
- CLI only, no dashboard

**Phase 2 — Expand the roster**
- Add `@debugger`, `@tester`, `@docs`
- Add SQLite memory + session history
- Add `@context-broker` (needs the most memory maturity, so it comes later)

**Phase 3 — Full system**
- Web dashboard
- Multi-provider support turned on (add OpenAI/local adapter)
- Background/autonomous mode (repo-watching agents)
- Open-source readiness pass: config/secrets separation, docs, install script

---

## 5. Tech Stack (finalized)

| Layer | Choice | Why |
|---|---|---|
| Agent core / orchestrator | Python | matches your backend stack, best AI/agent ecosystem |
| Model abstraction | **Custom thin adapter** (`generate`/`stream`/`tool_call` interface, implemented per-provider) | full control over tool-calling reliability, no black-box dependency behavior |
| API layer (CLI/web ↔ orchestrator) | **FastAPI** | async-native, WebSocket support for streaming agent output to both CLI and dashboard |
| Python packaging | **uv** | fast, modern, solid lockfile discipline |
| Tool execution / sandboxing | **Permission tiers**: read-only skills run free; mutating skills (write/commit/push) require confirmation; destructive ops (force-push, delete) always confirm, even in background mode | balances safety with background-agent usability |
| CLI framework | **Typer** (+ Rich for TUI output) | type-hint driven, pairs cleanly with Rich for streaming/diff rendering |
| Local database | **SQLAlchemy + Alembic** | full ORM with proper migrations as schema grows across agents/sessions |
| Web dashboard | **Vite + React (SPA)** | lightweight, local-only tool — no need for Next.js's SSR/deploy machinery |
| Code search/intelligence | **Tree-sitter (AST-aware)** from Phase 1 | structural queries ("find all callers of X") matter for review/debug/context-broker quality; scoped to Python + TS/JS grammars only, so upfront cost is bounded |
| Testing | **pytest (core) + Vitest (dashboard)**, from the start | standard pairing for this stack, keeps both sides covered as they grow together |

**Dependency shape:**
- Core: `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `typer`, `rich`, `tree-sitter` + language grammars, `pytest`
- Dashboard: `vite`, `react`, `vitest`, WebSocket client for streaming
- No LiteLLM — provider adapters implemented directly, starting with Anthropic

---

## 6. Open Questions for Next Session
- Repo scope: mono-repo aware? Multi-repo workspace concept?
- Cost controls: per-agent budget/rate limiting given multi-agent runs multiply API spend?
- Naming/branding if this eventually goes public?
- Exact shape of the provider adapter interface — what does `tool_call` need to normalize across Claude/GPT/local models?

---

## 7. Next Steps
1. Scaffold the repo structure (Python core + orchestrator skeleton, uv-managed).
2. Define the provider adapter interface and implement the Anthropic adapter.
3. Build `@reviewer` end-to-end as the walking skeleton for the whole system — this exercises the orchestrator, permission-tier execution, FastAPI streaming, and Tree-sitter search all at once.
