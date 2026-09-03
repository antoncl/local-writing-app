"""ADR-0081 slice 1 — the one metadata-ref traversal + the three integrity passes
retrofitted onto it, proven to reach a reference nested inside an item_group.

The gate is still closed (slice 2 opens schema authoring of ref-member groups), so
these build the schema + metadata directly in memory — a group with an
`entity_ref` member and a value carrying a nested ref — and drive the traversal
and the passes over it. ★ marks the mutation-critical traps: a top-level-only
implementation slips through them silently (an unindexed backlink, an unscrubbed
nested ref on delete — the silent mis-link).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.models.schema import (
    EntryTypeDefinition,
    GroupMember,
    MetadataFieldDefinition,
    MetadataSchema,
)
from app.services.project.metadata_refs import (
    UNCHANGED,
    iter_ref_occurrences,
    rewrite_ref_occurrences,
)
from app.services.project.node_index import NodeIndexEntry
from app.services.project_service import ProjectService


def _schema() -> MetadataSchema:
    """A character with a top-level `pov` ref, a `rels` list whose item_group has an
    `entity_ref` member `who` (+ a scalar `kind`), and an `aka` scalar-sugar list."""
    return MetadataSchema(
        fields={
            "pov": MetadataFieldDefinition(name="POV", type="entity_ref"),
            "rels": MetadataFieldDefinition(
                name="Relationships",
                type="list",
                item_group="rel",
                item_scalar=False,
                item_members=[
                    GroupMember(key="who", name="Who", type="entity_ref"),
                    GroupMember(key="kind", name="Kind", type="select"),
                ],
            ),
            "aka": MetadataFieldDefinition(
                name="Aliases", type="list", item_type="text", item_scalar=True,
                item_members=[GroupMember(key="value", name="Value", type="text")],
            ),
        },
        entry_types={
            "character": EntryTypeDefinition(name="Character", kind="lore", fields=["pov", "rels", "aka"]),
        },
    )


def _metadata() -> dict:
    return {
        "pov": "char_a",
        "rels": [
            {"who": "char_b", "kind": "ally"},
            {"who": "char_c", "kind": "rival"},
        ],
        "aka": ["The Kid", "Slim"],
    }


# --- the traversal itself -----------------------------------------------------


def test_iter_finds_top_level_and_nested_refs_but_not_scalar_sugar() -> None:
    occ = list(iter_ref_occurrences(_metadata(), _schema()))
    found = {(o.field_id, o.member_key, o.value) for o in occ}
    assert found == {
        ("pov", None, "char_a"),
        ("rels", "who", "char_b"),
        ("rels", "who", "char_c"),
    }
    # The scalar-sugar `aka` list holds no ref members, so it yields nothing.
    assert all(o.field_id != "aka" for o in occ)
    # A nested occurrence carries the member-as-field, so its type/picker travel.
    nested = next(o for o in occ if o.member_key == "who")
    assert nested.field.type == "entity_ref"


def test_rewrite_scrubs_a_nested_ref_without_mutating_the_input() -> None:
    metadata = _metadata()

    def scrub(occ):  # drop char_b wherever it lives
        return "" if occ.value == "char_b" else UNCHANGED

    cleaned, changed = rewrite_ref_occurrences(metadata, _schema(), scrub)

    assert changed is True
    assert cleaned["rels"][0]["who"] == ""          # nested ref scrubbed
    assert cleaned["rels"][1]["who"] == "char_c"     # sibling item untouched
    assert cleaned["rels"][0]["kind"] == "ally"      # sibling member untouched
    assert cleaned["pov"] == "char_a"                # untouched top-level field
    # ★ the input is not mutated (copy-on-write, not aliased).
    assert metadata["rels"][0]["who"] == "char_b"
    assert metadata["rels"] is not cleaned["rels"]   # the changed list was cloned


def test_rewrite_with_no_change_is_a_cheap_noop() -> None:
    metadata = _metadata()
    cleaned, changed = rewrite_ref_occurrences(metadata, _schema(), lambda _o: UNCHANGED)
    assert changed is False
    # An unchanged list is never cloned — copy-on-write stays cheap on the read path.
    assert cleaned["rels"] is metadata["rels"]


# --- the three integrity passes, retrofitted onto the traversal ---------------


def test_purge_scrubs_a_nested_ref_to_a_deleted_node() -> None:
    # ★ delete-scrubs-nested — the silent-mis-link trap. A top-level-only purge
    # leaves the nested ref pointing at a deleted node.
    service = ProjectService(None)
    cleaned, changed = service._purge_metadata_refs(_metadata(), _schema(), {"char_b"})
    assert changed is True
    assert cleaned["rels"][0]["who"] == ""
    assert cleaned["rels"][1]["who"] == "char_c"
    assert cleaned["pov"] == "char_a"


def test_strip_hides_a_nested_dangling_ref_and_keeps_a_live_one() -> None:
    # ★ heal-nested. char_a and char_c exist in the index; char_b was deleted.
    service = ProjectService(None)
    node_index = SimpleNamespace(by_id={"char_a": object(), "char_c": object()})
    cleaned = service._strip_dangling_references(_metadata(), _schema(), node_index)
    assert cleaned["rels"][0]["who"] == ""           # dangling nested ref hidden
    assert cleaned["rels"][1]["who"] == "char_c"     # live nested ref kept
    assert cleaned["pov"] == "char_a"                # live top-level ref kept


def test_resolve_reference_titles_swaps_a_nested_id_for_its_title() -> None:
    # ADR-0081 slice 2: display resolution reaches a nested ref, so it shows the
    # target's title, not a raw id.
    service = ProjectService(None)
    node_index = SimpleNamespace(
        by_id={
            "char_a": SimpleNamespace(title="Alice"),
            "char_b": SimpleNamespace(title="Bob"),
            "char_c": SimpleNamespace(title="Cara"),
        }
    )
    resolved = service._resolve_reference_titles(_metadata(), "character", _schema(), node_index)
    assert resolved["pov"] == "Alice"            # top-level ref → title
    assert resolved["rels"][0]["who"] == "Bob"    # nested ref → title
    assert resolved["rels"][1]["who"] == "Cara"
    assert resolved["rels"][0]["kind"] == "ally"  # sibling member untouched


def test_reference_edges_include_a_nested_ref() -> None:
    # ★ backlinks-find-nested. The reference graph must have an edge from the
    # group member, or char_b/char_c have no backlink to this node.
    service = ProjectService(None)
    entry = NodeIndexEntry(id="src", kind="lore", entry_type="character", path=Path("src.md"))
    edges = service._reference_edges_for_entry(
        entry, _schema(), front_matter={"metadata": _metadata()}
    )
    targets = {(e.dst, e.field_id) for e in edges}
    assert ("char_a", "pov") in targets      # top-level still works
    assert ("char_b", "rels") in targets     # nested edge, keyed on the list field
    assert ("char_c", "rels") in targets
