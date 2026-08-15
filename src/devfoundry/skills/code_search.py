"""code.search: AST-aware symbol search over Python and TypeScript/JS
source, via Tree-sitter (spec 3.3, spec 5's finalized tech stack).

READ_ONLY per spec's tech-stack table — declared explicitly via @tier so
it still routes through PermissionGate for a single audit trail (spec
3.1), even though that tier never triggers a confirmation prompt (mirrors
git_ops.git_diff).

Design notes (see docs/spec.md 3.3, 5):
- One public entrypoint, `code_search`, with a `kind` filter rather than
  separate find_definition()/find_references() functions — one skill, one
  permission-gate call site, one audit-trail entry.
- Python and TypeScript/JS are dispatched internally by file extension via
  `_Grammar`; callers never see Tree-sitter's Language/Parser/Query types,
  only `SearchResult`.
- No caching, no persistent index: every call re-parses the requested
  files from disk. Agents can edit files between calls, so a cached index
  would need an invalidation story this phase doesn't have yet (that's
  spec 3.5's Phase 2 SQLite index territory) — parsing fresh is the
  simplest approach that's still correct.
- Reference matching is AST-shaped (only real call syntax counts, not
  arbitrary text occurrences) but not semantically scoped: two different
  `foo`s shadowed in different scopes/files both match a search for
  "foo". Good enough for "find all callers of X" as a context-gathering
  step; full scope resolution is future work if it turns out to matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tree_sitter import Language, Node, Parser, Query, QueryCursor

from devfoundry.skills.permissions import SkillTier, tier

try:
    import tree_sitter_python as _tspython
    import tree_sitter_typescript as _tstypescript
except ImportError as exc:  # pragma: no cover - dependency is in pyproject
    raise ImportError(
        "code_search requires tree-sitter language grammars "
        "(tree-sitter-python, tree-sitter-typescript) to be installed."
    ) from exc

_IGNORED_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}

SearchKind = Literal["definition", "reference", "all"]


class SkillError(Exception):
    """Raised when code_search can't complete — bad path, unreadable file,
    etc. Mirrors git_ops.SkillError / github_ops.SkillError: callers never
    need to catch Tree-sitter's or the filesystem's exception types
    directly."""


@dataclass(frozen=True)
class SearchResult:
    """One match. `start_line`/`end_line` are 1-indexed and inclusive,
    spanning the full matched node (e.g. a definition's whole body) so a
    caller can follow up with a future code.read for full context.
    `snippet` is only the source line at `start_line`, trimmed — a preview
    for scanning results, not the full body."""

    file: Path
    symbol: str
    kind: str  # "function" | "class" | "method" | "call"
    start_line: int
    end_line: int
    snippet: str
    language: str  # "python" | "typescript"


@dataclass(frozen=True)
class _Grammar:
    """One language's Tree-sitter parser plus its precompiled definition
    and call queries. Queries are static (pattern strings never change
    based on file content) so compiling them once per language at import
    time is just avoiding repeat work — not an index, and not something
    that can go stale."""

    language_tag: str
    parser: Parser
    definition_query: Query
    call_query: Query
    # Tree-sitter node type -> our result "kind", for definition matches.
    def_node_kind: dict[str, str]

    def is_method(self, def_node: Node) -> bool:
        """Python has no distinct grammar node for "method" — a
        function_definition inside a class body is one. TS/JS grammars
        already distinguish method_definition from function_declaration,
        so this is only ever consulted for Python's function_definition
        nodes (see def_node_kind)."""
        parent = def_node.parent  # "block"
        grandparent = parent.parent if parent else None
        return grandparent is not None and grandparent.type == "class_definition"


_PY_DEFINITION_QUERY = """
(function_definition name: (identifier) @name) @def
(class_definition name: (identifier) @name) @def
"""
_PY_CALL_QUERY = """
(call function: (identifier) @name) @call
(call function: (attribute attribute: (identifier) @name)) @call
"""

_TS_DEFINITION_QUERY = """
(function_declaration name: (identifier) @name) @def
(class_declaration name: (type_identifier) @name) @def
(method_definition name: (property_identifier) @name) @def
"""
_TS_CALL_QUERY = """
(call_expression function: (identifier) @name) @call
(call_expression function: (member_expression property: (property_identifier) @name)) @call
"""


def _build_python_grammar() -> _Grammar:
    language = Language(_tspython.language())
    return _Grammar(
        language_tag="python",
        parser=Parser(language),
        definition_query=Query(language, _PY_DEFINITION_QUERY),
        call_query=Query(language, _PY_CALL_QUERY),
        def_node_kind={"function_definition": "function", "class_definition": "class"},
    )


def _build_typescript_grammar(language: Language) -> _Grammar:
    return _Grammar(
        language_tag="typescript",
        parser=Parser(language),
        definition_query=Query(language, _TS_DEFINITION_QUERY),
        call_query=Query(language, _TS_CALL_QUERY),
        def_node_kind={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
        },
    )


# Extension -> grammar. .ts/.js use the plain TypeScript grammar; .tsx/.jsx
# need the TSX grammar for JSX syntax. Both tag results "typescript" —
# which grammar handled a file is an implementation detail callers
# shouldn't need to know.
_GRAMMARS: dict[str, _Grammar] = {
    ".py": _build_python_grammar(),
    ".ts": _build_typescript_grammar(Language(_tstypescript.language_typescript())),
    ".js": _build_typescript_grammar(Language(_tstypescript.language_typescript())),
    ".tsx": _build_typescript_grammar(Language(_tstypescript.language_tsx())),
    ".jsx": _build_typescript_grammar(Language(_tstypescript.language_tsx())),
}


def _iter_source_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path.exists():
            raise SkillError(f"code_search path does not exist: {path}")
        if path.is_file():
            files.append(path)
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file():
                continue
            if any(part in _IGNORED_DIR_NAMES for part in candidate.parts):
                continue
            if candidate.suffix in _GRAMMARS:
                files.append(candidate)
    return files


def _line_snippet(source_lines: list[bytes], line_1indexed: int) -> str:
    raw = source_lines[line_1indexed - 1] if 0 < line_1indexed <= len(source_lines) else b""
    text = raw.decode("utf-8", errors="replace").strip()
    return text if len(text) <= 200 else text[:200] + "…"


def _search_file(file_path: Path, symbol: str, kind: SearchKind) -> list[SearchResult]:
    grammar = _GRAMMARS.get(file_path.suffix)
    if grammar is None:
        return []

    try:
        source = file_path.read_bytes()
    except OSError as exc:
        raise SkillError(f"could not read {file_path}: {exc}") from exc

    tree = grammar.parser.parse(source)
    source_lines = source.splitlines()
    results: list[SearchResult] = []

    if kind in ("definition", "all"):
        cursor = QueryCursor(grammar.definition_query)
        for _pattern_index, captures in cursor.matches(tree.root_node):
            name_nodes = captures.get("name", [])
            def_nodes = captures.get("def", [])
            if not name_nodes or not def_nodes:
                continue
            name_node, def_node = name_nodes[0], def_nodes[0]
            if name_node.text is None or name_node.text.decode("utf-8") != symbol:
                continue
            result_kind = grammar.def_node_kind.get(def_node.type, def_node.type)
            if result_kind == "function" and grammar.is_method(def_node):
                result_kind = "method"
            start_line = def_node.start_point[0] + 1
            results.append(
                SearchResult(
                    file=file_path,
                    symbol=symbol,
                    kind=result_kind,
                    start_line=start_line,
                    end_line=def_node.end_point[0] + 1,
                    snippet=_line_snippet(source_lines, start_line),
                    language=grammar.language_tag,
                )
            )

    if kind in ("reference", "all"):
        cursor = QueryCursor(grammar.call_query)
        for _pattern_index, captures in cursor.matches(tree.root_node):
            name_nodes = captures.get("name", [])
            call_nodes = captures.get("call", [])
            if not name_nodes or not call_nodes:
                continue
            name_node, call_node = name_nodes[0], call_nodes[0]
            if name_node.text is None or name_node.text.decode("utf-8") != symbol:
                continue
            start_line = call_node.start_point[0] + 1
            results.append(
                SearchResult(
                    file=file_path,
                    symbol=symbol,
                    kind="call",
                    start_line=start_line,
                    end_line=call_node.end_point[0] + 1,
                    snippet=_line_snippet(source_lines, start_line),
                    language=grammar.language_tag,
                )
            )

    return results


@tier(SkillTier.READ_ONLY)
def code_search(
    paths: str | Path | list[str | Path],
    symbol: str,
    *,
    kind: SearchKind = "all",
) -> list[SearchResult]:
    """Search Python/TypeScript/JS source for a symbol's definitions
    and/or call sites, via Tree-sitter (spec 3.3).

    `paths` may be a single file, a single directory (walked recursively,
    skipping .git/__pycache__/node_modules/.venv), or a list of either.
    Files with unrecognized extensions are silently skipped.

    `kind="definition"` returns function/class/method definitions named
    `symbol`. `kind="reference"` returns call sites — `symbol(...)` and
    `obj.symbol(...)` — matched by AST call syntax, not text search, but
    not scope-resolved (see module docstring). `kind="all"` (default)
    returns both.

    Raises SkillError if `symbol` is empty, any given path doesn't exist,
    or a matched source file can't be read.

    Every call re-parses the requested files from disk — no caching, so
    results always reflect the current on-disk state (see module
    docstring on why that's the right tradeoff for Phase 1).
    """
    if not symbol.strip():
        raise SkillError("code_search requires a non-empty symbol name.")

    path_list = [Path(paths)] if isinstance(paths, (str, Path)) else [Path(p) for p in paths]
    if not path_list:
        raise SkillError("code_search requires at least one path.")

    results: list[SearchResult] = []
    for file_path in _iter_source_files(path_list):
        results.extend(_search_file(file_path, symbol, kind))
    return results