"""Send-time implicit-context expander — pure function over (project, text,
journal, picks). Returns NEW journal entries; never mutates state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import (
    ChatSessionContextItem,
    ChatSessionJournalEntry,
    CreateLoreEntryRequest,
    SaveLoreEntryRequest,
)
from app.services.ai.context_expander import expand_context
from app.services.project_service import ProjectService


# ---- fixture --------------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Project with three characters wired similarly to the test_ai_helpers
    fixture: Honor (with alias "The Salamander"), Nimitz, and Pavel Young
    (whom Honor's body textually mentions — feeds the depth-1 path).
    """
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    svc = ProjectService()
    svc.create_project(tmp_path / "project", "Demo")

    honor = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Honor Harrington", entry_type="character")
    )
    nimitz = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Nimitz", entry_type="character")
    )
    pavel = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Pavel Young", entry_type="character")
    )

    def _save(entry_id, *, metadata, body):
        existing = svc.read_lore_entry(entry_id)
        svc.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=existing.title,
                body_markdown=body,
                base_revision=existing.revision,
                entry_type="character",
                metadata=metadata,
            ),
        )

    _save(
        honor.id,
        # "Honor" alone is realistic — writers refer to the protagonist by
        # first name far more often than by full name. Without this the
        # matcher would only fire on the full "Honor Harrington".
        metadata={"aliases": ["The Salamander", "Honor"]},
        body="Captain of the Fearless. Rival of Pavel Young.",
    )
    _save(nimitz.id, metadata={"aliases": []}, body="Honor's treecat.")
    _save(pavel.id, metadata={"aliases": []}, body="Disgraced Captain.")

    svc._honor_id = honor.id
    svc._nimitz_id = nimitz.id
    svc._pavel_id = pavel.id
    return svc


# ---- tests ----------------------------------------------------------------


def test_empty_text_returns_no_entries(project):
    assert expand_context(project, "") == []
    assert expand_context(project, "   \n  ") == []


def test_no_matches_returns_no_entries(project):
    out = expand_context(project, "Just some prose with no character names.")
    assert out == []


def test_direct_match_labeled_with_caller_source(project):
    out = expand_context(project, "Honor stepped onto the bridge.", source="user_message", turn=3)
    assert len(out) == 2  # Honor (direct) + Pavel (depth1 via Honor's body)
    honor = next(e for e in out if e.entry_id == project._honor_id)
    pavel = next(e for e in out if e.entry_id == project._pavel_id)
    assert honor.source == "user_message"
    assert honor.added_at_turn == 3
    assert honor.title == "Honor Harrington"
    assert honor.entry_type == "character"
    assert pavel.source == "depth1_expansion"
    assert pavel.added_at_turn == 3


def test_alias_match_works(project):
    # "The Salamander" is Honor's alias — should resolve to Honor.
    out = expand_context(project, "The Salamander returned from Manticore.")
    ids = {e.entry_id for e in out}
    assert project._honor_id in ids


def test_dedup_against_existing_journal(project):
    existing = [
        ChatSessionJournalEntry(entry_id=project._honor_id, title="Honor"),
    ]
    out = expand_context(
        project, "Honor and Nimitz arrived together.", existing_journal=existing
    )
    ids = {e.entry_id for e in out}
    # Honor was already in journal — NOT re-added.
    assert project._honor_id not in ids
    # Nimitz is new — included.
    assert project._nimitz_id in ids


def test_dedup_against_explicit_lore_picks(project):
    picks = [
        ChatSessionContextItem(kind="lore", id=project._honor_id, title="Honor"),
    ]
    out = expand_context(project, "Honor and Nimitz arrived.", explicit_picks=picks)
    ids = {e.entry_id for e in out}
    assert project._honor_id not in ids  # excluded by explicit pick
    assert project._nimitz_id in ids


def test_explicit_picks_of_other_kinds_dont_dedup(project):
    # A scene/snippet/preset pick should NOT shadow a lore detection
    # even if ids collide (separate identity spaces).
    picks = [
        ChatSessionContextItem(kind="scene", id=project._honor_id, title="x"),
    ]
    out = expand_context(project, "Honor arrived.", explicit_picks=picks)
    ids = {e.entry_id for e in out}
    assert project._honor_id in ids


def test_depth1_does_not_recurse(project):
    # Pavel's body mentions no other characters. Honor's body mentions
    # Pavel. So a scan triggered by Honor should pull Pavel (depth-1)
    # but no further. We assert by adding a fourth character mentioned
    # only in Pavel's body and confirming it is NOT pulled.
    anders = project.create_lore_entry(
        CreateLoreEntryRequest(title="Anders Pierce", entry_type="character")
    )
    existing = project.read_lore_entry(anders.id)
    project.save_lore_entry(
        anders.id,
        SaveLoreEntryRequest(
            title=existing.title,
            body_markdown="Some text.",
            base_revision=existing.revision,
            entry_type="character",
            metadata={"aliases": []},
        ),
    )
    pavel = project.read_lore_entry(project._pavel_id)
    project.save_lore_entry(
        project._pavel_id,
        SaveLoreEntryRequest(
            title=pavel.title,
            body_markdown="Disgraced Captain. Friend of Anders Pierce.",
            base_revision=pavel.revision,
            entry_type="character",
            metadata={"aliases": []},
        ),
    )

    out = expand_context(project, "Honor returned.")
    ids = {e.entry_id for e in out}
    assert project._honor_id in ids
    assert project._pavel_id in ids       # depth 1
    assert anders.id not in ids           # depth 2 — must stop


def test_dedup_is_set_union(project):
    # Both journal AND picks can shadow.
    existing = [
        ChatSessionJournalEntry(entry_id=project._honor_id, title="Honor"),
    ]
    picks = [
        ChatSessionContextItem(kind="lore", id=project._nimitz_id, title="Nimitz"),
    ]
    out = expand_context(
        project,
        "Honor and Nimitz and Pavel Young met.",
        existing_journal=existing,
        explicit_picks=picks,
    )
    ids = {e.entry_id for e in out}
    assert project._honor_id not in ids   # shadowed by journal
    assert project._nimitz_id not in ids  # shadowed by pick
    assert project._pavel_id in ids       # truly new
