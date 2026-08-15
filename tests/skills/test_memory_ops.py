from __future__ import annotations

from pathlib import Path

import pytest

from devfoundry.skills.memory_ops import (
    SkillError,
    get_project_context,
    read_config,
    read_decisions,
    read_note,
    record_decision,
    write_config,
    write_note,
)
from devfoundry.skills.permissions import SkillTier, get_tier

# --- permission tiers -----------------------------------------------------


@pytest.mark.parametrize(
    "fn,expected",
    [
        (record_decision, SkillTier.MUTATING),
        (write_note, SkillTier.MUTATING),
        (write_config, SkillTier.MUTATING),
        (read_decisions, SkillTier.READ_ONLY),
        (read_note, SkillTier.READ_ONLY),
        (read_config, SkillTier.READ_ONLY),
        (get_project_context, SkillTier.READ_ONLY),
    ],
)
def test_declared_tiers(fn, expected):
    assert get_tier(fn) == expected


# --- record_decision / read_decisions -------------------------------------


def test_read_decisions_empty_when_no_file(tmp_path: Path):
    assert read_decisions(tmp_path) == []


def test_record_decision_creates_log_and_returns_entry(tmp_path: Path):
    entry = record_decision(tmp_path, "Use JSON for configs", "No new dependency.", tags=["memory"])

    assert entry.title == "Use JSON for configs"
    assert entry.tags == ["memory"]
    assert entry.body == "No new dependency."
    assert entry.date  # today's date, ISO format

    log = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert log.startswith("# Decisions Log")
    assert "## " + entry.date + " - Use JSON for configs" in log
    assert "Tags: memory" in log
    assert "No new dependency." in log


def test_record_decision_without_tags_omits_tags_line(tmp_path: Path):
    record_decision(tmp_path, "Title", "Body")

    log = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert "Tags:" not in log


def test_record_decision_appends_in_order(tmp_path: Path):
    record_decision(tmp_path, "First decision", "Body one.")
    record_decision(tmp_path, "Second decision", "Body two.")

    entries = read_decisions(tmp_path)

    assert [e.title for e in entries] == ["First decision", "Second decision"]


def test_record_decision_raises_on_empty_title(tmp_path: Path):
    with pytest.raises(SkillError):
        record_decision(tmp_path, "   ", "Body")


def test_record_decision_raises_on_empty_body(tmp_path: Path):
    with pytest.raises(SkillError):
        record_decision(tmp_path, "Title", "   ")


def test_read_decisions_limit_returns_most_recent_oldest_first(tmp_path: Path):
    for i in range(5):
        record_decision(tmp_path, f"Decision {i}", f"Body {i}.")

    entries = read_decisions(tmp_path, limit=2)

    assert [e.title for e in entries] == ["Decision 3", "Decision 4"]


def test_read_decisions_filters_by_tag_case_insensitive(tmp_path: Path):
    record_decision(tmp_path, "Tagged", "Body.", tags=["Architecture"])
    record_decision(tmp_path, "Untagged", "Body.")

    entries = read_decisions(tmp_path, tag="architecture")

    assert [e.title for e in entries] == ["Tagged"]


def test_read_decisions_raises_on_malformed_heading(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "decisions.md").write_text(
        "# Decisions Log\n\n## not a valid heading\n\nbody\n", encoding="utf-8"
    )

    with pytest.raises(SkillError):
        read_decisions(tmp_path)


# --- write_note / read_note -------------------------------------------------


def test_write_note_then_read_note_round_trips(tmp_path: Path):
    path = write_note(tmp_path, "architecture", "# Architecture\n\nDetails.")

    assert path == tmp_path / "memory" / "notes" / "architecture.md"
    assert read_note(tmp_path, "architecture") == "# Architecture\n\nDetails."


def test_write_note_adds_md_extension_if_missing(tmp_path: Path):
    write_note(tmp_path, "auth.md", "content")

    assert (tmp_path / "memory" / "notes" / "auth.md").exists()
    assert read_note(tmp_path, "auth") == "content"


def test_write_note_overwrites_existing(tmp_path: Path):
    write_note(tmp_path, "note", "first")
    write_note(tmp_path, "note", "second")

    assert read_note(tmp_path, "note") == "second"


def test_read_note_raises_when_missing(tmp_path: Path):
    with pytest.raises(SkillError):
        read_note(tmp_path, "missing")


@pytest.mark.parametrize("bad_name", ["", "   ", "../escape", "sub/dir", "a\\b", "."])
def test_note_name_validation_rejects_unsafe_names(tmp_path: Path, bad_name: str):
    with pytest.raises(SkillError):
        write_note(tmp_path, bad_name, "content")


# --- write_config / read_config --------------------------------------------


def test_write_config_then_read_config_round_trips(tmp_path: Path):
    path = write_config(tmp_path, "reviewer", {"model": "claude", "scope": ["diff"]})

    assert path == tmp_path / "memory" / "configs" / "reviewer.json"
    assert read_config(tmp_path, "reviewer") == {"model": "claude", "scope": ["diff"]}


def test_write_config_adds_json_extension_if_missing(tmp_path: Path):
    write_config(tmp_path, "docs.json", {"a": 1})

    assert (tmp_path / "memory" / "configs" / "docs.json").exists()


def test_write_config_raises_on_non_serializable(tmp_path: Path):
    with pytest.raises(SkillError):
        write_config(tmp_path, "bad", {"obj": object()})


def test_read_config_raises_when_missing(tmp_path: Path):
    with pytest.raises(SkillError):
        read_config(tmp_path, "missing")


def test_read_config_raises_on_invalid_json(tmp_path: Path):
    configs_dir = tmp_path / "memory" / "configs"
    configs_dir.mkdir(parents=True)
    (configs_dir / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(SkillError):
        read_config(tmp_path, "broken")


# --- get_project_context ----------------------------------------------------


def test_get_project_context_spec_none_when_missing(tmp_path: Path):
    context = get_project_context(tmp_path)

    assert context.spec is None
    assert context.recent_decisions == []
    assert context.note_names == []
    assert context.config_names == []


def test_get_project_context_bundles_everything(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "spec.md").write_text("# Spec\n", encoding="utf-8")
    record_decision(tmp_path, "Decision", "Body.")
    write_note(tmp_path, "b-note", "content")
    write_note(tmp_path, "a-note", "content")
    write_config(tmp_path, "reviewer", {"model": "claude"})

    context = get_project_context(tmp_path)

    assert context.spec == "# Spec\n"
    assert [e.title for e in context.recent_decisions] == ["Decision"]
    assert context.note_names == ["a-note", "b-note"]
    assert context.config_names == ["reviewer"]


def test_get_project_context_decision_limit(tmp_path: Path):
    for i in range(3):
        record_decision(tmp_path, f"Decision {i}", "Body.")

    context = get_project_context(tmp_path, decision_limit=1)

    assert [e.title for e in context.recent_decisions] == ["Decision 2"]