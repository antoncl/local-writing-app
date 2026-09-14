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
from app.models_views import NodePickerConfig
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
    node_index = SimpleNamespace(
        by_id={"char_a": object(), "char_c": object()}, canonical_id=lambda node_id: node_id
    )
    cleaned = service._strip_dangling_references(_metadata(), _schema(), node_index)
    assert cleaned["rels"][0]["who"] == ""           # dangling nested ref hidden
    assert cleaned["rels"][1]["who"] == "char_c"     # live nested ref kept
    assert cleaned["pov"] == "char_a"                # live top-level ref kept


def test_traversal_reaches_a_nested_entity_ref_list_member() -> None:
    # ADR-0081 slice 3: a ref-LIST member (not just a scalar entity_ref) rides
    # the same traversal, so it must yield + rewrite a list value inside a
    # group member — the shape a tag vocabulary itself now uses (ADR-0082
    # slice 2b: the `tags` field type is retired in favour of entity_ref_list).
    schema = MetadataSchema(
        fields={
            "meta": MetadataFieldDefinition(
                name="Meta",
                type="list",
                item_group="m",
                item_scalar=False,
                item_members=[GroupMember(key="topic", name="Topic", type="entity_ref_list")],
            ),
        },
    )
    metadata = {"meta": [{"topic": ["a", "b"]}, {"topic": ["c"]}]}
    occ = [(o.field_id, o.member_key, o.field.type, o.value) for o in iter_ref_occurrences(metadata, schema)]
    assert occ == [
        ("meta", "topic", "entity_ref_list", ["a", "b"]),
        ("meta", "topic", "entity_ref_list", ["c"]),
    ]

    cleaned, changed = rewrite_ref_occurrences(metadata, schema, lambda o: [t.upper() for t in o.value])
    assert changed is True
    assert cleaned["meta"][0]["topic"] == ["A", "B"]
    assert cleaned["meta"][1]["topic"] == ["C"]
    assert metadata["meta"][0]["topic"] == ["a", "b"]  # input unmutated


def test_resolve_reference_titles_swaps_a_nested_id_for_its_title() -> None:
    # ADR-0081 slice 2: display resolution reaches a nested ref, so it shows the
    # target's title, not a raw id.
    service = ProjectService(None)
    node_index = SimpleNamespace(
        by_id={
            "char_a": SimpleNamespace(title="Alice"),
            "char_b": SimpleNamespace(title="Bob"),
            "char_c": SimpleNamespace(title="Cara"),
        },
        canonical_id=lambda node_id: node_id,
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


# --- ADR-0074 Amendment 4: FAMILY (`descendants_of`) picker scope ------------
#
# A picker/tag scope may whitelist an entry_type EXACTLY (`{type: fqn}`) or as
# a FAMILY (`{descendants_of: fqn}`, self + subtypes). `_ref_matches_picker`
# (read-side heal) and `_validate_reference_target` (save/AI-patch) must both
# accept a target whose entry_type is EXACTLY scoped OR is-a one of the scoped
# FAMILY roots — never the reverse (a parent accepted under a child's scope).


def _family_schema() -> MetadataSchema:
    """`lore:character` and its `lore:character:deity` sub-type (parent chain),
    each field carrying a picker_config exercising a different scope shape:
    `family_field` is FAMILY-scoped to `lore:character` (self + subtypes),
    `exact_field` is EXACT-scoped to `lore:character` only, and
    `deity_family_field` is FAMILY-scoped to the deity sub-type itself — so a
    plain `lore:character` (deity's own parent) must NOT match it; a reversed
    is-a arg order would wrongly accept it (the parent is an ancestor of the
    scoped root, not a descendant)."""
    return MetadataSchema(
        fields={
            "family_field": MetadataFieldDefinition(
                name="Family Patron",
                type="entity_ref",
                picker_config=NodePickerConfig.from_membership(
                    kinds=["lore"],
                    entry_types={"lore": ["lore:character"]},
                    families={"lore": ["lore:character"]},
                ),
            ),
            "exact_field": MetadataFieldDefinition(
                name="Exact Patron",
                type="entity_ref",
                picker_config=NodePickerConfig.from_membership(
                    kinds=["lore"], entry_types={"lore": ["lore:character"]}
                ),
            ),
            "deity_family_field": MetadataFieldDefinition(
                name="Deity-only Family",
                type="entity_ref",
                picker_config=NodePickerConfig.from_membership(
                    kinds=["lore"],
                    entry_types={"lore": ["lore:character:deity"]},
                    families={"lore": ["lore:character:deity"]},
                ),
            ),
        },
        entry_types={
            "lore:character": EntryTypeDefinition(
                name="Character", kind="lore", fields=["family_field", "exact_field", "deity_family_field"]
            ),
            "lore:character:deity": EntryTypeDefinition(
                name="Deity",
                kind="lore",
                parent="lore:character",
                fields=["family_field", "exact_field", "deity_family_field"],
            ),
        },
    )


def _family_node_index() -> SimpleNamespace:
    return SimpleNamespace(
        by_id={
            "deity_1": NodeIndexEntry(
                id="deity_1", kind="lore", entry_type="lore:character:deity", path=Path("deity_1.md")
            ),
            "char_1": NodeIndexEntry(
                id="char_1", kind="lore", entry_type="lore:character", path=Path("char_1.md")
            ),
        },
        canonical_id=lambda node_id: node_id,
    )


def test_validate_reference_target_accepts_a_subtype_under_a_family_scope_but_not_exact() -> None:
    schema = _family_schema()
    node_index = _family_node_index()
    service = ProjectService(None)
    family_field = schema.fields["family_field"]
    exact_field = schema.fields["exact_field"]

    assert (
        service._validate_reference_target(
            "Entry", "family_field", "deity_1", family_field, node_index, schema
        )
        == []
    )
    exact_errors = service._validate_reference_target(
        "Entry", "exact_field", "deity_1", exact_field, node_index, schema
    )
    assert exact_errors != []


def test_ref_matches_picker_accepts_a_subtype_under_a_family_scope_but_not_exact() -> None:
    schema = _family_schema()
    node_index = _family_node_index()
    service = ProjectService(None)
    family_field = schema.fields["family_field"]
    exact_field = schema.fields["exact_field"]

    assert service._ref_matches_picker("deity_1", family_field, node_index, schema) is True
    assert service._ref_matches_picker("deity_1", exact_field, node_index, schema) is False


def test_family_scope_is_a_arg_order_does_not_accept_a_parent_under_a_child_scope() -> None:
    # ★ arg-order trap: a scope FAMILY-rooted at the deity sub-type must not
    # accept a plain `lore:character` node — `lore:character` is deity's
    # ANCESTOR, not a descendant. A reversed `_entry_type_matches(family_root,
    # target.entry_type, schema)` call would wrongly say yes (a parent IS in
    # its own ancestry-of-itself lookup direction reversed).
    schema = _family_schema()
    node_index = _family_node_index()
    service = ProjectService(None)
    deity_family_field = schema.fields["deity_family_field"]

    errors = service._validate_reference_target(
        "Entry", "deity_family_field", "char_1", deity_family_field, node_index, schema
    )
    assert errors != []
    assert service._ref_matches_picker("char_1", deity_family_field, node_index, schema) is False
    # The deity itself, self + subtypes of the scoped root, still matches.
    assert (
        service._validate_reference_target(
            "Entry", "deity_family_field", "deity_1", deity_family_field, node_index, schema
        )
        == []
    )
