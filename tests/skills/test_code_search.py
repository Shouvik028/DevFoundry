"""Tests run against real fixture files with the actual Tree-sitter
grammars (no mocking) — parsing behavior is exactly what's worth testing
for real here, unlike an external API. See tests/skills/fixtures/."""

from __future__ import annotations

from pathlib import Path

import pytest

from devfoundry.skills.code_search import SkillError, code_search
from devfoundry.skills.permissions import SkillTier, get_tier

FIXTURES = Path(__file__).parent / "fixtures"
PY_FIXTURE = FIXTURES / "sample.py"
TS_FIXTURE = FIXTURES / "sample.ts"


def test_code_search_is_read_only_tier():
    assert get_tier(code_search) == SkillTier.READ_ONLY


# --- Python: definitions ---------------------------------------------------


def test_python_finds_function_definition():
    results = code_search(PY_FIXTURE, "greet", kind="definition")

    functions = [r for r in results if r.kind == "function"]
    assert len(functions) == 1
    result = functions[0]
    assert result.file == PY_FIXTURE
    assert result.language == "python"
    assert result.start_line == 1
    assert "def greet(name):" in result.snippet


def test_python_finds_class_and_method_definitions():
    results = code_search(PY_FIXTURE, "greet", kind="definition")

    kinds = {r.kind for r in results}
    assert "method" in kinds  # Greeter.greet, distinguished from the top-level function
    method = next(r for r in results if r.kind == "method")
    assert method.start_line == 6

    class_results = code_search(PY_FIXTURE, "Greeter", kind="definition")
    assert len(class_results) == 1
    assert class_results[0].kind == "class"


def test_python_finds_call_sites():
    results = code_search(PY_FIXTURE, "greet", kind="reference")

    # greet(name) inside Greeter.greet, g.greet("world") (attribute call
    # matched by name, not scope-resolved — see module docstring), and
    # greet("standalone") inside main().
    assert len(results) == 3
    assert all(r.kind == "call" for r in results)
    lines = {r.start_line for r in results}
    assert lines == {7, 12, 13}


def test_python_finds_method_call_via_attribute():
    # g.greet("world") is an attribute call whose attribute name matches
    # the searched symbol — matched by name (not resolved to which
    # `greet` it targets), consistent with the module's documented
    # "AST-shaped, not semantically scoped" reference matching.
    results = code_search(PY_FIXTURE, "greet", kind="reference")
    assert any("g.greet" in r.snippet for r in results)


def test_python_kind_all_returns_both_definitions_and_references():
    results = code_search(PY_FIXTURE, "greet", kind="all")

    kinds = {r.kind for r in results}
    assert "function" in kinds
    assert "method" in kinds
    assert "call" in kinds


# --- TypeScript: definitions -----------------------------------------------


def test_typescript_finds_function_definition():
    results = code_search(TS_FIXTURE, "greet", kind="definition")

    functions = [r for r in results if r.kind == "function"]
    assert len(functions) == 1
    result = functions[0]
    assert result.language == "typescript"
    assert result.start_line == 1
    assert "function greet" in result.snippet


def test_typescript_finds_class_and_method_definitions():
    results = code_search(TS_FIXTURE, "greet", kind="definition")

    kinds = {r.kind for r in results}
    assert "method" in kinds
    method = next(r for r in results if r.kind == "method")
    assert method.start_line == 6

    class_results = code_search(TS_FIXTURE, "Greeter", kind="definition")
    assert len(class_results) == 1
    assert class_results[0].kind == "class"


def test_typescript_finds_call_sites():
    results = code_search(TS_FIXTURE, "greet", kind="reference")

    # return greet(name), g.greet("world"), and greet("standalone").
    assert len(results) == 3
    assert all(r.kind == "call" for r in results)
    lines = {r.start_line for r in results}
    assert lines == {7, 13, 14}


def test_typescript_member_call_matches_method_name():
    # g.greet("world") is a member call on property "greet" — matches a
    # search for symbol "greet" via the member_expression call pattern
    # (matched by name, not scope-resolved — see module docstring).
    results = code_search(TS_FIXTURE, "greet", kind="reference")
    snippets = " ".join(r.snippet for r in results)
    assert "g.greet" in snippets
    assert 'greet("standalone")' in snippets


# --- Directory search / multi-file, multi-language --------------------------


def test_directory_search_covers_both_languages():
    results = code_search(FIXTURES, "greet", kind="definition")

    languages = {r.language for r in results}
    assert languages == {"python", "typescript"}


def test_list_of_paths_is_accepted():
    results = code_search([PY_FIXTURE, TS_FIXTURE], "Greeter", kind="definition")
    assert len(results) == 2


# --- Errors and edge cases ---------------------------------------------------


def test_raises_for_nonexistent_path():
    with pytest.raises(SkillError):
        code_search(FIXTURES / "does_not_exist.py", "greet")


def test_raises_for_empty_symbol():
    with pytest.raises(SkillError):
        code_search(PY_FIXTURE, "   ")


def test_no_match_returns_empty_list():
    assert code_search(PY_FIXTURE, "nonexistent_symbol") == []


def test_unrecognized_extension_is_silently_skipped(tmp_path: Path):
    (tmp_path / "readme.md").write_text("greet is mentioned here but isn't code")
    assert code_search(tmp_path, "greet") == []


def test_directory_search_ignores_dunder_pycache(tmp_path: Path):
    ignored_dir = tmp_path / "__pycache__"
    ignored_dir.mkdir()
    (ignored_dir / "sample.py").write_text("def greet(name):\n    return name\n")
    assert code_search(tmp_path, "greet") == []