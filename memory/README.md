# Memory (file-based)

This directory is the git-tracked half of DevFoundry's memory layer (spec
3.5): project knowledge that should be human-readable, diffable, and
reviewable in PRs. It is managed through the `memory.query` / `memory.write`
skills (`src/devfoundry/skills/memory_ops.py`), though every file here is
plain Markdown/JSON and safe to read or hand-edit directly.

Deliberately **not** under `.devfoundry/` — that directory is gitignored
and reserved for Phase 2 runtime state (SQLite db, logs, embeddings/index).
Memory that belongs in git lives here instead.

The project spec itself is not duplicated here — see
[`docs/spec.md`](../docs/spec.md), which is already git-tracked file-based
memory. `get_project_context()` reads it directly.

## Layout

- `decisions.md` — append-only decisions log, oldest entry first. Written
  via `record_decision()`, read via `read_decisions()`. Entry format:

  ```
  ## YYYY-MM-DD - Title
  Tags: comma, separated, tags (optional)

  Body text, one or more paragraphs.
  ```

- `notes/<name>.md` — architecture notes and other freeform project
  knowledge. Written via `write_note()`, read via `read_note()`. Each
  write overwrites the whole file; there's no revision history beyond
  what git already gives you.

- `configs/<name>.json` — structured agent/skill configuration. Written
  via `write_config()`, read via `read_config()`.

## Permission tier

All writes (`record_decision`, `write_note`, `write_config`) are
`SkillTier.MUTATING` — the same tier as `github_pr_comment` — so they
route through confirmation before running. See the module docstring in
`memory_ops.py` for why local, git-reversible file writes still warrant
that tier rather than a lighter one.