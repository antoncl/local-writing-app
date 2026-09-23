"""Send-time implicit-context expander — pure function over (project, text,
journal, picks). Returns NEW journal entries; never mutates state.
"""

from __future__ import annotations

import pytest

from app.models import (
    ChatSessionJournalEntry,
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    UpsertMetadataFieldRequest,
)
from app.services.ai.context_expander import expand_context
from app.services.project_service import ProjectService

# ---- fixture --------------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Project with three characters wired similarly to the test_ai_helpers
    fixture: Honor (with alias "The Salamander"), Nimitz, and Pavel Young
    (whom Honor's body textually mentions — feeds the depth-1 path).

    `lore:character` also carries a custom `notes` `long_text` field (#2147) —
    unset by default on every entry, so it changes nothing for tests that
    don't use it — for the depth-1 hop's own prose-surface (body + long_text)
    tests.
    """
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    svc = ProjectService.created_at(tmp_path / "project", "Demo")

    layer_id = svc._metadata_schema_layer_id(svc.root_path)
    svc.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layer_id,
            field_id="notes",
            field=MetadataFieldDefinition(name="Notes", type="long_text"),
            entry_type="lore:character",
        )
    )

    honor = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
    )
    nimitz = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character")
    )
    pavel = svc.create_lore_entry(
        CreateLoreEntryRequest(title="Pavel Young", entry_type="lore:character")
    )

    def _save(entry_id, *, metadata, body):
        existing = svc.read_lore_entry(entry_id)
        svc.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                entry_type="lore:character",
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


def _set_notes(project, entry_id, notes):
    existing = project.read_lore_entry(entry_id)
    project.save_lore_entry(
        entry_id,
        SaveLoreEntryRequest(
            title=existing.title,
            body=existing.body,
            base_revision=existing.revision,
            entry_type="lore:character",
            metadata={**existing.metadata, "notes": notes},
        ),
    )


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
    assert honor.entry_type == "lore:character"
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


def test_dedup_against_picked_ids(project):
    # Picker-resolved lore (tags/views/containers/nodes) rides in used_node_ids
    # and is passed as `picked_ids` (#1634). A picked entry that is also
    # mentioned must NOT be re-journaled as auto-added.
    out = expand_context(
        project, "Honor and Nimitz arrived.", picked_ids=[project._honor_id]
    )
    ids = {e.entry_id for e in out}
    assert project._honor_id not in ids  # excluded: already in context via the pick
    assert project._nimitz_id in ids  # genuinely auto-detected, kept


def test_picked_ids_exclude_depth1_matches(project):
    # The reported case: the subject (Honor) is picked; its body mentions Pavel,
    # so Pavel would be pulled in via depth-1 expansion. If Pavel is ALSO picked,
    # it must not surface as auto-added.
    out = expand_context(
        project,
        "Honor stepped onto the bridge.",
        picked_ids=[project._honor_id, project._pavel_id],
    )
    assert out == []  # both the direct and the depth-1 match are picks


def test_depth1_does_not_recurse(project):
    # Pavel's body mentions no other characters. Honor's body mentions
    # Pavel. So a scan triggered by Honor should pull Pavel (depth-1)
    # but no further. We assert by adding a fourth character mentioned
    # only in Pavel's body and confirming it is NOT pulled.
    anders = project.create_lore_entry(
        CreateLoreEntryRequest(title="Anders Pierce", entry_type="lore:character")
    )
    existing = project.read_lore_entry(anders.id)
    project.save_lore_entry(
        anders.id,
        SaveLoreEntryRequest(
            title=existing.title,
            body="Some text.",
            base_revision=existing.revision,
            entry_type="lore:character",
            metadata={"aliases": []},
        ),
    )
    pavel = project.read_lore_entry(project._pavel_id)
    project.save_lore_entry(
        project._pavel_id,
        SaveLoreEntryRequest(
            title=pavel.title,
            body="Disgraced Captain. Friend of Anders Pierce.",
            base_revision=pavel.revision,
            entry_type="lore:character",
            metadata={"aliases": []},
        ),
    )

    out = expand_context(project, "Honor returned.")
    ids = {e.entry_id for e in out}
    assert project._honor_id in ids
    assert project._pavel_id in ids       # depth 1
    assert anders.id not in ids           # depth 2 — must stop


# ---- #2147: the hop's prose surface matches detection's --------------------
# Detection (`_scene_prose_ids`) scans a scene's body PLUS every `long_text`
# field; the depth-1 hop must scan the same surface on each seed it walks, via
# the same shared collector (`_prose_texts`).


def test_depth1_expansion_from_a_seeds_long_text_field(project):
    # Honor's `notes` (long_text) names Nimitz — nowhere in Honor's body.
    # The hop must still pull Nimitz in, exactly as it already does for a
    # body mention (Pavel).
    _set_notes(project, project._honor_id, "Grew up alongside Nimitz.")

    out = expand_context(project, "Honor stepped onto the bridge.")
    by_id = {e.entry_id: e for e in out}
    assert by_id[project._honor_id].source == "user_message"
    assert by_id[project._pavel_id].source == "depth1_expansion"  # body, as before
    assert by_id[project._nimitz_id].source == "depth1_expansion"  # long_text, #2147


def test_depth1_does_not_scan_a_hop_founds_long_text_field(project):
    # Pavel is a hop-found entry (via Honor's body). Depth stays strictly
    # one: a name in PAVEL's own `notes` field must not be pulled in.
    anders = project.create_lore_entry(
        CreateLoreEntryRequest(title="Anders Pierce", entry_type="lore:character")
    )
    _set_notes(project, project._pavel_id, "Old friend of Anders Pierce.")

    out = expand_context(project, "Honor returned.")
    ids = {e.entry_id for e in out}
    assert project._pavel_id in ids   # depth 1, via Honor's body
    assert anders.id not in ids       # depth 2 through a long_text field — must stop


def test_depth1_name_split_across_body_and_long_text_is_not_falsely_joined(project):
    # A multi-word name straddling the seed's body end and its long_text
    # field start must not false-match, on the hop just as on detection
    # (`_scene_prose_ids`'s own field-boundary test) — the two texts are
    # scanned SEPARATELY and unioned, never concatenated.
    bob_smith = project.create_lore_entry(
        CreateLoreEntryRequest(title="Bob Smith", entry_type="lore:character")
    )
    existing = project.read_lore_entry(bob_smith.id)
    project.save_lore_entry(
        bob_smith.id,
        SaveLoreEntryRequest(
            title=existing.title,
            body="A quiet man.",
            base_revision=existing.revision,
            entry_type="lore:character",
            metadata={"aliases": []},
        ),
    )
    honor = project.read_lore_entry(project._honor_id)
    project.save_lore_entry(
        project._honor_id,
        SaveLoreEntryRequest(
            title=honor.title,
            body="Captain of the Fearless. Introduced herself as Bob",
            base_revision=honor.revision,
            entry_type="lore:character",
            metadata=honor.metadata,
        ),
    )
    _set_notes(project, project._honor_id, "Smith gave a curt nod and said nothing else.")

    out = expand_context(project, "Honor returned.")
    ids = {e.entry_id for e in out}
    assert bob_smith.id not in ids


def test_dedup_is_set_union(project):
    # Both journal AND picks can shadow.
    existing = [
        ChatSessionJournalEntry(entry_id=project._honor_id, title="Honor"),
    ]
    out = expand_context(
        project,
        "Honor and Nimitz and Pavel Young met.",
        existing_journal=existing,
        picked_ids=[project._nimitz_id],
    )
    ids = {e.entry_id for e in out}
    assert project._honor_id not in ids   # shadowed by journal
    assert project._nimitz_id not in ids  # shadowed by pick
    assert project._pavel_id in ids       # truly new


# ---- ADR-0086 Amendment 1 (#1887): monotone precedence -----------------------
# A mention from a source ranked strictly better than any the journal holds for
# that id appends one more entry under that source; the same or a worse rank
# adds nothing. Rank order: user_message < rendered_prompt < scene_prose <
# depth1_expansion.


def _pavel_journaled_as(project, source: str) -> list[ChatSessionJournalEntry]:
    return [
        ChatSessionJournalEntry(
            entry_id=project._pavel_id, title="Pavel Young", added_at_turn=1, source=source
        )
    ]


@pytest.mark.parametrize(
    ("journaled_as", "promoted"),
    [
        ("depth1_expansion", True),  # the hop → the author names him
        ("scene_prose", True),  # the scene named him → the author names him
        ("rendered_prompt", True),  # the prompt named him → the author names him
        ("user_message", False),  # the author already named him: no refresh
    ],
)
def test_the_authors_mention_promotes_only_a_worse_ranked_entry(project, journaled_as, promoted):
    out = expand_context(
        project, "What does Pavel Young want?",
        existing_journal=_pavel_journaled_as(project, journaled_as), turn=3,
    )
    expected = [(project._pavel_id, "user_message", 3)] if promoted else []
    assert [(e.entry_id, e.source, e.added_at_turn) for e in out] == expected


@pytest.mark.parametrize(
    ("journaled_as", "promoted"),
    [
        ("depth1_expansion", True),  # a hop entry the prompt now names
        ("scene_prose", True),  # the scene's rank is worse than the prompt's
        ("rendered_prompt", False),  # same source: nothing
        ("user_message", False),  # the author outranks the prompt: nothing
    ],
)
def test_the_prompts_mention_promotes_only_a_worse_ranked_entry(project, journaled_as, promoted):
    out = expand_context(
        project, "", existing_journal=_pavel_journaled_as(project, journaled_as),
        rendered_text="Pavel Young.", turn=3,
    )
    expected = [(project._pavel_id, "rendered_prompt", 3)] if promoted else []
    assert [(e.entry_id, e.source, e.added_at_turn) for e in out] == expected


def test_a_hop_rehit_never_promotes(project):
    # Honor's body mentions Pavel; naming HONOR re-finds Pavel through the hop
    # only. Whatever the journal holds for Pavel is at least as good as the
    # hop, so nothing is added for him — a hop cannot promote anything.
    for journaled_as in ("depth1_expansion", "scene_prose", "user_message"):
        out = expand_context(
            project, "Honor paces the bridge.",
            existing_journal=_pavel_journaled_as(project, journaled_as), turn=3,
        )
        assert [e.entry_id for e in out] == [project._honor_id], journaled_as


def test_a_picked_entry_is_never_promoted(project):
    # A pick is already sent through its own channel: naming it journals nothing.
    out = expand_context(
        project, "Pavel Young.",
        existing_journal=_pavel_journaled_as(project, "depth1_expansion"),
        picked_ids=[project._pavel_id], turn=3,
    )
    assert out == []
