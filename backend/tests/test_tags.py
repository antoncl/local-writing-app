"""The layered tag registry (#339).

`tags.yaml` was the one roster the hierarchy never walked: `read_known_tags` read
the open project's file and nothing else, so an ancestor-owned lore entry — which
`list_lore_entries` has always shown — carried tags the picker could not suggest
and the next save re-registered as new, into the wrong layer.

Two invariants carry most of these tests:

* **Tags union, they do not shadow.** Unlike a node, the same tag may be asserted
  at several layers; the merged record is the union of their scopes, stamped with
  every asserting layer.
* **A layer's file records what that layer asserted, never the resolved scope.**
  All three registry writers read merged and rewrite a whole file, so layering the
  read without splitting the two views turns every one of them into a flattener —
  silently, on the next save, with no author action. That is what
  `test_saving_does_not_copy_ancestor_tags_into_the_project` pins.

There was no test file for tags at all before this one; `read_known_tags`,
`update_tag_scope`, `merge_tags` and `read_tags_overview` were entirely uncovered.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    MergeTagsRequest,
    NodePickerConfig,
    UpdateTagColorRequest,
    UpdateTagScopeRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


def _scope(kind: str, entry_type: str) -> dict:
    return NodePickerConfig.from_membership(
        kinds=[kind], entry_types={kind: [entry_type]}
    ).model_dump(exclude_none=True)


class LayeredTagsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: on Windows `TemporaryDirectory()` returns the 8.3 short form
        # (C:\Users\RUNNER~1\...) while the layer walk canonicalises, so an
        # unresolved fixture compares unequal to the folders it returns (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _write_layer_tags(self, folder: Path, tags: list[dict]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(folder / "tags.yaml", {"tags": tags})

    def _layer_id(self, folder: Path) -> str:
        return next(
            layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder
        )

    def _raw_tags(self, folder: Path) -> list[dict]:
        return self.service._read_yaml(folder / "tags.yaml").get("tags", [])

    # --- read ----------------------------------------------------------

    def test_merged_read_unions_ancestor_and_project_registries(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_layer_tags(self.root, [{"name": "grayson", "scope": {}}])

        names = [tag.name for tag in self.service.read_known_tags().tags]

        self.assertEqual(names, ["grayson", "treecat"])

    def test_merged_tag_carries_every_asserting_layer(self) -> None:
        # Provenance is a SET, not a single source_layer_id: a tag does not
        # shadow, so "which layer owns it" has no single answer. #313 branches on
        # this to tell "this layer asserts it" from "this layer inherits it".
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_layer_tags(self.root, [{"name": "treecat", "scope": {}}])

        tag = self.service.read_known_tags().tags[0]

        self.assertEqual(
            [ref.id for ref in tag.source_layers],
            [self._layer_id(self.universe), self._layer_id(self.root)],
        )

    def test_inherited_only_tag_is_not_stamped_with_the_open_project(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])

        tag = self.service.read_known_tags().tags[0]

        self.assertEqual([ref.label for ref in tag.source_layers], ["honorverse"])

    def test_scopes_union_across_layers(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "naval", "scope": _scope("lore", "lore:character")}])
        self._write_layer_tags(self.root, [{"name": "naval", "scope": _scope("lore", "lore:location")}])

        tag = self.service.read_known_tags().tags[0]

        self.assertEqual(sorted(tag.scope.entry_types["lore"]), ["lore:character", "lore:location"])

    def test_first_seen_casing_wins_and_the_outermost_layer_is_first(self) -> None:
        # Iteration runs outermost → root, so casing belongs to the layer that
        # introduced the tag: a book's typo cannot restyle the world's vocabulary.
        self._write_layer_tags(self.universe, [{"name": "Treecat", "scope": {}}])
        self._write_layer_tags(self.root, [{"name": "treecat", "scope": {}}])

        self.assertEqual([tag.name for tag in self.service.read_known_tags().tags], ["Treecat"])

    # --- truncation at an authoring level -------------------------------

    def test_reading_at_a_layer_drops_layers_below_it(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_layer_tags(self.series, [{"name": "manticore", "scope": {}}])
        self._write_layer_tags(self.root, [{"name": "grayson", "scope": {}}])

        names = [
            tag.name
            for tag in self.service.read_known_tags(up_to_layer_id=self._layer_id(self.series)).tags
        ]

        # Ancestors of the authoring level stay visible — truncation reaches
        # down, never up. A series-targeted write must not be able to use
        # vocabulary that exists only at the book.
        self.assertEqual(names, ["manticore", "treecat"])

    def test_reading_at_an_unknown_layer_fails_loudly(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "Unknown layer"):
            self.service.read_known_tags(up_to_layer_id="nosuchlayer")

    # --- the flattening hazard -----------------------------------------
    #
    # The save-time registration/canonicalisation these tests used to pin
    # (`_canonicalise_metadata_tags`) retired with the `tags` field TYPE
    # (ADR-0082 slice 2b) — a tag vocabulary is now an `entity_ref_list` field,
    # which does not canonicalise free text or auto-register new names on
    # save. What's left below is the REGISTRY itself (scope/colour/merge over
    # `tags.yaml`, directly written/read here), which TagsMixin still serves
    # unchanged pending its slice-4 removal.

    # --- bounded writers ------------------------------------------------

    def test_inherited_tag_scope_cannot_be_narrowed(self) -> None:
        # Scope composes by union, so a narrower local record cannot shadow the
        # ancestor's — the write would simply have no effect on the next read.
        # TagManagerDialog has no layer selector, so fail loudly instead.
        self._write_layer_tags(
            self.universe,
            [{"name": "naval", "scope": NodePickerConfig.from_membership(kinds=["lore"]).model_dump(exclude_none=True)}],
        )

        with self.assertRaisesRegex(ProjectServiceError, "widened here, not narrowed"):
            self.service.update_tag_scope(
                UpdateTagScopeRequest(
                    name="naval",
                    scope=NodePickerConfig.from_membership(
                        kinds=["lore"], entry_types={"lore": ["lore:character"]}
                    ),
                )
            )

    def test_broadening_an_inherited_tag_records_only_the_local_delta(self) -> None:
        # The dialog seeds its draft from the merged overview, so the request
        # carries the RESOLVED scope. Recording that verbatim would re-assert the
        # ancestor's membership here forever — the world could later narrow or
        # drop `naval` and the book would go on claiming lore:character.
        self._write_layer_tags(
            self.universe,
            [{"name": "naval", "scope": _scope("lore", "lore:character")}],
        )

        self.service.update_tag_scope(
            UpdateTagScopeRequest(
                name="naval",
                scope=NodePickerConfig.from_membership(
                    kinds=["lore"], entry_types={"lore": ["lore:character", "lore:location"]}
                ),
            )
        )

        self.assertEqual(
            self._raw_tags(self.universe),
            [{"name": "naval", "scope": _scope("lore", "lore:character")}],
        )
        self.assertEqual(
            self._raw_tags(self.root),
            [{"name": "naval", "scope": _scope("lore", "lore:location")}],
        )
        merged = self.service.read_known_tags().tags[0]
        self.assertEqual(sorted(merged.scope.entry_types["lore"]), ["lore:character", "lore:location"])

    def test_scope_edit_fully_covered_by_inheritance_records_nothing(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "naval", "scope": _scope("lore", "lore:character")}])
        self._write_layer_tags(self.root, [{"name": "naval", "scope": _scope("lore", "lore:character")}])

        self.service.update_tag_scope(
            UpdateTagScopeRequest(
                name="naval",
                scope=NodePickerConfig.from_membership(kinds=["lore"], entry_types={"lore": ["lore:character"]}),
            )
        )

        self.assertEqual(self._raw_tags(self.root), [])

    def test_merging_an_inherited_tag_is_refused(self) -> None:
        # A rename may only rewrite records and documents at or below the
        # authoring level. Reaching higher is what ADR-0042's dropdown forbids —
        # and the ancestor's record would survive the merge anyway, so the tag
        # would reappear on the next read.
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_layer_tags(self.root, [{"name": "cats", "scope": {}}])

        with self.assertRaisesRegex(ProjectServiceError, "used in a parent folder"):
            self.service.merge_tags(MergeTagsRequest(sources=["treecat"], target="cats"))

    def test_merging_into_an_inherited_target_keeps_the_ancestor_scope_upstream(self) -> None:
        # The target may be inherited even when every source is local. Seeding the
        # union from the merged record would make this layer assert a scope the
        # ancestor authored.
        self._write_layer_tags(self.universe, [{"name": "magic", "scope": _scope("lore", "lore:spell")}])
        self._write_layer_tags(self.root, [{"name": "sorcery", "scope": _scope("lore", "lore:artifact")}])

        self.service.merge_tags(MergeTagsRequest(sources=["sorcery"], target="magic"))

        self.assertEqual(
            self._raw_tags(self.root),
            [{"name": "magic", "scope": _scope("lore", "lore:artifact")}],
        )
        self.assertEqual(
            self._raw_tags(self.universe),
            [{"name": "magic", "scope": _scope("lore", "lore:spell")}],
        )

    def test_merging_local_tags_still_works_and_writes_only_here(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_layer_tags(
            self.root,
            [
                {"name": "cats", "scope": _scope("lore", "lore:character")},
                {"name": "felines", "scope": _scope("lore", "lore:location")},
            ],
        )

        self.service.merge_tags(MergeTagsRequest(sources=["felines"], target="cats"))

        root_tags = self._raw_tags(self.root)
        self.assertEqual([tag["name"] for tag in root_tags], ["cats"])
        self.assertEqual(
            sorted(NodePickerConfig.model_validate(root_tags[0]["scope"]).entry_types["lore"]),
            ["lore:character", "lore:location"],
        )
        self.assertEqual([tag["name"] for tag in self._raw_tags(self.universe)], ["treecat"])

    # --- overview -------------------------------------------------------
    #
    # `test_usage_counts_span_the_layer_chain` (a document usage-count over a
    # `tags`-typed field) retired with the field TYPE (ADR-0082 slice 2b):
    # `_count_document_tags` now matches no schema field, so a document usage
    # count is always 0 — see `TagsMixin._count_document_tags`'s own docstring.

    # --- colour (#247) --------------------------------------------------

    def test_read_carries_a_tags_colour(self) -> None:
        self._write_layer_tags(self.root, [{"name": "grayson", "scope": {}, "color": "forest"}])

        tag = self.service.read_known_tags().tags[0]

        self.assertEqual(tag.color, "forest")

    def test_nearer_layer_colour_wins(self) -> None:
        # Colour is a single value, not a union like scope: the nearest asserting
        # layer overrides. The book recolours the world's tag.
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}, "color": "slate"}])
        self._write_layer_tags(self.root, [{"name": "treecat", "scope": {}, "color": "forest"}])

        self.assertEqual(self.service.read_known_tags().tags[0].color, "forest")

    def test_ancestor_colour_is_inherited_when_the_nearer_layer_has_none(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}, "color": "slate"}])
        self._write_layer_tags(self.root, [{"name": "treecat", "scope": {}}])

        self.assertEqual(self.service.read_known_tags().tags[0].color, "slate")

    def test_update_tag_color_writes_a_local_record(self) -> None:
        self._write_layer_tags(self.root, [{"name": "grayson", "scope": {}}])

        self.service.update_tag_color(UpdateTagColorRequest(name="grayson", color="forest"))

        raw = self._raw_tags(self.root)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["name"], "grayson")
        self.assertEqual(raw[0]["color"], "forest")
        self.assertEqual(self.service.read_known_tags().tags[0].color, "forest")

    def test_colouring_an_inherited_tag_does_not_widen_its_scope(self) -> None:
        # Colouring an inherited-only tag writes a local record with an EMPTY
        # scope; that empty scope must contribute no sources to the merged union,
        # or the tag would silently broaden to "everywhere".
        self._write_layer_tags(
            self.universe, [{"name": "naval", "scope": _scope("lore", "lore:character")}]
        )

        self.service.update_tag_color(UpdateTagColorRequest(name="naval", color="forest"))

        tag = self.service.read_known_tags().tags[0]
        self.assertEqual(tag.color, "forest")
        self.assertEqual(tag.scope.entry_types["lore"], ["lore:character"])
        self.assertEqual(tag.scope.kinds, ["lore"])

    def test_clearing_colour_drops_a_bare_local_record(self) -> None:
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}, "color": "slate"}])
        self.service.update_tag_color(UpdateTagColorRequest(name="treecat", color="forest"))

        self.service.update_tag_color(UpdateTagColorRequest(name="treecat", color=None))

        # The local color-only assertion is gone; the ancestor's colour resurfaces.
        self.assertEqual(self._raw_tags(self.root), [])
        self.assertEqual(self.service.read_known_tags().tags[0].color, "slate")

    def test_clearing_colour_keeps_a_locally_scoped_record(self) -> None:
        self._write_layer_tags(
            self.root, [{"name": "naval", "scope": _scope("lore", "lore:character"), "color": "forest"}]
        )

        self.service.update_tag_color(UpdateTagColorRequest(name="naval", color=None))

        # The scope is a real local assertion, so the record survives — only the
        # colour is dropped.
        self.assertEqual(self._raw_tags(self.root), [{"name": "naval", "scope": _scope("lore", "lore:character")}])

    def test_merge_survivor_keeps_its_own_colour(self) -> None:
        self._write_layer_tags(
            self.root,
            [
                {"name": "navy", "scope": {}, "color": "forest"},
                {"name": "fleet", "scope": {}, "color": "slate"},
            ],
        )

        self.service.merge_tags(MergeTagsRequest(sources=["fleet"], target="navy"))

        tag = next(tag for tag in self.service.read_known_tags().tags if tag.name == "navy")
        self.assertEqual(tag.color, "forest")

    def test_overview_carries_colour(self) -> None:
        self._write_layer_tags(self.root, [{"name": "grayson", "scope": {}, "color": "forest"}])

        usage = next(usage for usage in self.service.read_tags_overview().tags if usage.name == "grayson")

        self.assertEqual(usage.color, "forest")

    # `test_saving_a_broadened_coloured_tag_keeps_its_colour` (a save-time
    # scope auto-broaden) retired with the `tags` field TYPE (ADR-0082 slice
    # 2b) along with `_canonicalise_metadata_tags`; scope broadening survives
    # only through the direct registry writers below (`update_tag_scope`).

    def test_editing_scope_keeps_the_tags_colour(self) -> None:
        self._write_layer_tags(
            self.root, [{"name": "hero", "scope": _scope("lore", "lore:character"), "color": "forest"}]
        )
        wider = NodePickerConfig.from_membership(
            kinds=["lore"], entry_types={"lore": ["lore:character", "lore:location"]}
        )

        self.service.update_tag_scope(UpdateTagScopeRequest(name="hero", scope=wider))

        tag = next(tag for tag in self.service.read_known_tags().tags if tag.name == "hero")
        self.assertEqual(tag.color, "forest")

    def test_scope_edit_fully_covered_by_inheritance_keeps_local_colour(self) -> None:
        # Ancestor scopes 'naval'; book colours it (a colour-only local record);
        # re-asserting exactly the inherited scope leaves an empty delta — the
        # colour-only record must survive rather than being popped.
        self._write_layer_tags(
            self.universe, [{"name": "naval", "scope": _scope("lore", "lore:character")}]
        )
        self.service.update_tag_color(UpdateTagColorRequest(name="naval", color="forest"))
        inherited = NodePickerConfig.from_membership(kinds=["lore"], entry_types={"lore": ["lore:character"]})

        self.service.update_tag_scope(UpdateTagScopeRequest(name="naval", scope=inherited))

        tag = next(tag for tag in self.service.read_known_tags().tags if tag.name == "naval")
        self.assertEqual(tag.color, "forest")

    def test_a_malformed_colour_scalar_reads_as_neutral(self) -> None:
        # A hand-edited/imported record with a non-string colour must read as
        # neutral, never raise out of every tags read AND the scene-save path.
        self._write_layer_tags(self.root, [{"name": "naval", "scope": {}, "color": 1}])

        tag = self.service.read_known_tags().tags[0]

        self.assertEqual(tag.name, "naval")
        self.assertIsNone(tag.color)

    def test_merge_survivor_without_colour_does_not_inherit_a_sources_colour(self) -> None:
        # The discriminating case: survivor has NO colour, a source does — the
        # source colour must NOT fold in (it drops with the source record).
        self._write_layer_tags(
            self.root,
            [
                {"name": "navy", "scope": {}},
                {"name": "fleet", "scope": {}, "color": "slate"},
            ],
        )

        self.service.merge_tags(MergeTagsRequest(sources=["fleet"], target="navy"))

        tag = next(tag for tag in self.service.read_known_tags().tags if tag.name == "navy")
        self.assertIsNone(tag.color)


if __name__ == "__main__":
    unittest.main()
