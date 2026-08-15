"""memory.query / memory.write skills (spec 3.3) — the file-based half of
the memory layer (spec 3.5): "files (git-tracked, per-project): project
spec, architecture notes, agent/skill configs, decisions log —
human-readable, diffable, reviewable in PRs." SQLite/session-history
memory is Phase 2 (spec 4), out of scope here.

Storage lives under `<repo_root>/memory/` — a plain, git-tracked
directory, deliberately *not* under `.devfoundry/` (that's gitignored and
reserved for Phase 2 runtime state: SQLite db, logs, index). See
`memory/README.md` for the human-facing layout description.

Structured, purpose-specific functions rather than a generic
memory_write(key, content)/memory_read(key) pair: decisions, notes, and
configs have genuinely different read/write semantics (append-only log vs.
overwrite-a-file vs. structured JSON), so collapsing them into one
key/content shape would just push that structure back onto every caller.
This mirrors how git_ops.py is expected to grow (git_blame, git_bisect,
... per spec 3.3) — one function per operation, not one mega-dispatcher.

Permission tier: every write here (record_decision, write_note,
write_config) is SkillTier.MUTATING, the same tier as
github_ops.github_pr_comment. Spec 5's stated trigger for confirmation is
"write" ("mutating skills (write/commit/push) require confirmation"), not
"has an external side effect" — these functions write persistent project
state (a decisions log meant to be a trustworthy record; configs other
agents will read) that an agent could get wrong just as easily as a PR
comment. permissions.py's own docstring already anticipates the resulting
tradeoff: "If a background/unattended mode is added later, only MUTATING
should ever become eligible for a pre-approved policy" — so confirmation
noise on frequent writes (e.g. an agent recording a decision after every
task) is a deliberately deferred cost, not an oversight. Reads
(read_decisions, read_note, read_config, get_project_context) are
READ_ONLY, same as git_ops/code_search.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from devfoundry.skills.permissions import SkillTier, tier

_DECISIONS_FILENAME = "decisions.md"
_DECISIONS_HEADER = "# Decisions Log\n"
_NOTES_DIRNAME = "notes"
_CONFIGS_DIRNAME = "configs"
_SPEC_PATH = Path("docs/spec.md")

# Matches a decision heading line, e.g. "2026-08-15 - Title here" (the
# leading "## " is stripped by _parse_decisions's block split before this
# runs against it).
_ENTRY_HEADING_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}) - (?P<title>.+)$")


class SkillError(Exception):
    """Raised when a memory skill can't complete — invalid name, malformed
    decisions.md entry, missing note/config, non-JSON-serializable config,
    etc. Mirrors git_ops.SkillError / github_ops.SkillError: callers never
    need to catch filesystem/json exception types directly."""


@dataclass(frozen=True)
class DecisionEntry:
    """One entry in decisions.md. `date` is ISO 8601 (YYYY-MM-DD)."""

    date: str
    title: str
    tags: list[str]
    body: str


@dataclass(frozen=True)
class ProjectContext:
    """Bundle for re-orientation (spec 3.2's @context-broker, or any agent
    starting a fresh task on this repo). `spec` is docs/spec.md's content
    — not duplicated under memory/, since that file is already git-tracked
    file-based memory in its own right."""

    spec: str | None
    recent_decisions: list[DecisionEntry]
    note_names: list[str]
    config_names: list[str]


def _memory_dir(repo_path: str | Path) -> Path:
    return Path(repo_path) / "memory"


def _safe_name(name: str) -> str:
    """Validate a user-supplied note/config name before it becomes a path
    component. Rejects empty names, path separators, and '.'/'..' —
    callers only ever get a flat file directly under notes/ or configs/,
    never an escape out of memory/."""
    if not name or not name.strip():
        raise SkillError("name must not be empty.")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise SkillError(
            f"invalid name {name!r}: must be a plain filename, no path separators."
        )
    return name


def _decisions_path(repo_path: str | Path) -> Path:
    return _memory_dir(repo_path) / _DECISIONS_FILENAME


def _parse_decisions(text: str) -> list[DecisionEntry]:
    entries: list[DecisionEntry] = []
    # Split on lines starting with "## " (each decision's heading).
    # blocks[0] is everything before the first heading (the "# Decisions
    # Log" preamble) and is discarded.
    blocks = re.split(r"(?m)^## ", text)
    for block in blocks[1:]:
        lines = block.splitlines()
        heading = lines[0].strip()
        match = _ENTRY_HEADING_RE.match(heading)
        if not match:
            raise SkillError(f"malformed decisions.md entry heading: {heading!r}")
        rest = lines[1:]
        tags: list[str] = []
        body_start = 0
        if rest and rest[0].strip().lower().startswith("tags:"):
            tags = [t.strip() for t in rest[0].split(":", 1)[1].split(",") if t.strip()]
            body_start = 1
        body = "\n".join(rest[body_start:]).strip()
        entries.append(
            DecisionEntry(
                date=match.group("date"),
                title=match.group("title").strip(),
                tags=tags,
                body=body,
            )
        )
    return entries


@tier(SkillTier.MUTATING)
def record_decision(
    repo_path: str | Path,
    title: str,
    body: str,
    *,
    tags: list[str] | None = None,
) -> DecisionEntry:
    """Append a decision to `memory/decisions.md`, creating the log (and
    `memory/`) if this is the first entry. Entries are dated with today's
    date and never edited or removed by this function — decisions.md is an
    append-only history (spec 3.5).

    Raises SkillError if `title` or `body` is empty.
    """
    if not title.strip():
        raise SkillError("record_decision requires a non-empty title.")
    if not body.strip():
        raise SkillError("record_decision requires a non-empty body.")

    entry = DecisionEntry(
        date=datetime.now().astimezone().date().isoformat(),
        title=title.strip(),
        tags=[t.strip() for t in (tags or []) if t.strip()],
        body=body.strip(),
    )

    path = _decisions_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_DECISIONS_HEADER, encoding="utf-8")

    lines = [f"## {entry.date} - {entry.title}"]
    if entry.tags:
        lines.append(f"Tags: {', '.join(entry.tags)}")
    lines.append("")
    lines.append(entry.body)
    block = "\n" + "\n".join(lines) + "\n"

    with path.open("a", encoding="utf-8") as f:
        f.write(block)

    return entry


@tier(SkillTier.READ_ONLY)
def read_decisions(
    repo_path: str | Path,
    *,
    limit: int | None = None,
    tag: str | None = None,
) -> list[DecisionEntry]:
    """Read `memory/decisions.md`, oldest first. `tag` filters to entries
    whose tags include it (case-insensitive). `limit` returns only the
    most recent N entries (applied after tag filtering) — i.e. the tail of
    the log, still oldest-to-newest.

    Returns an empty list if decisions.md doesn't exist yet. Raises
    SkillError if it exists but an entry heading can't be parsed.
    """
    path = _decisions_path(repo_path)
    if not path.exists():
        return []

    entries = _parse_decisions(path.read_text(encoding="utf-8"))
    if tag:
        entries = [e for e in entries if tag.lower() in (t.lower() for t in e.tags)]
    if limit is not None:
        entries = entries[-limit:]
    return entries


@tier(SkillTier.MUTATING)
def write_note(repo_path: str | Path, name: str, content: str) -> Path:
    """Create or overwrite an architecture/project note at
    `memory/notes/<name>.md`. `name` is a plain filename (no path
    separators) — the `.md` extension is added if not already present.

    Overwrites silently if the note already exists; there's no revision
    history here beyond what git already gives you. Callers that want an
    append-only trail should use record_decision instead.
    """
    name = _safe_name(name)
    if not name.endswith(".md"):
        name += ".md"
    notes_dir = _memory_dir(repo_path) / _NOTES_DIRNAME
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / name
    path.write_text(content, encoding="utf-8")
    return path


@tier(SkillTier.READ_ONLY)
def read_note(repo_path: str | Path, name: str) -> str:
    """Read `memory/notes/<name>.md`. Raises SkillError if it doesn't
    exist."""
    name = _safe_name(name)
    if not name.endswith(".md"):
        name += ".md"
    path = _memory_dir(repo_path) / _NOTES_DIRNAME / name
    if not path.exists():
        raise SkillError(f"no note named {name!r} in {path.parent}.")
    return path.read_text(encoding="utf-8")


@tier(SkillTier.MUTATING)
def write_config(repo_path: str | Path, name: str, config: dict[str, Any]) -> Path:
    """Write an agent/skill config as JSON to `memory/configs/<name>.json`
    (pretty-printed, keys sorted for stable diffs). Overwrites if it
    already exists. Raises SkillError if `config` isn't JSON-serializable.
    """
    name = _safe_name(name)
    if not name.endswith(".json"):
        name += ".json"
    configs_dir = _memory_dir(repo_path) / _CONFIGS_DIRNAME
    configs_dir.mkdir(parents=True, exist_ok=True)
    path = configs_dir / name
    try:
        serialized = json.dumps(config, indent=2, sort_keys=True) + "\n"
    except TypeError as exc:
        raise SkillError(f"config for {name!r} is not JSON-serializable: {exc}") from exc
    path.write_text(serialized, encoding="utf-8")
    return path


@tier(SkillTier.READ_ONLY)
def read_config(repo_path: str | Path, name: str) -> dict[str, Any]:
    """Read `memory/configs/<name>.json`. Raises SkillError if it doesn't
    exist or isn't valid JSON."""
    name = _safe_name(name)
    if not name.endswith(".json"):
        name += ".json"
    path = _memory_dir(repo_path) / _CONFIGS_DIRNAME / name
    if not path.exists():
        raise SkillError(f"no config named {name!r} in {path.parent}.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillError(f"config {name!r} is not valid JSON: {exc}") from exc


@tier(SkillTier.READ_ONLY)
def get_project_context(repo_path: str | Path, *, decision_limit: int = 5) -> ProjectContext:
    """Bundle project spec + recent decisions + available notes/configs
    into one read, for re-orientation (spec 3.2's @context-broker, or any
    agent starting a fresh task on this repo).

    `spec` is None if docs/spec.md doesn't exist (not every repo will have
    one). `recent_decisions` is the most recent `decision_limit` entries,
    oldest-to-newest. `note_names`/`config_names` are the available names
    (without extension) — callers fetch what they actually need via
    read_note()/read_config() rather than getting every file's full
    content up front.
    """
    repo_path = Path(repo_path)
    spec_path = repo_path / _SPEC_PATH
    spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else None

    recent_decisions = read_decisions(repo_path, limit=decision_limit)

    notes_dir = _memory_dir(repo_path) / _NOTES_DIRNAME
    note_names = sorted(p.stem for p in notes_dir.glob("*.md")) if notes_dir.exists() else []

    configs_dir = _memory_dir(repo_path) / _CONFIGS_DIRNAME
    config_names = (
        sorted(p.stem for p in configs_dir.glob("*.json")) if configs_dir.exists() else []
    )

    return ProjectContext(
        spec=spec,
        recent_decisions=recent_decisions,
        note_names=note_names,
        config_names=config_names,
    )