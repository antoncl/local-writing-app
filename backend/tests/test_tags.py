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

from app.models import (
    CreateLoreEntryRequest,
    MergeTagsRequest,
    NodePickerConfig,
    SaveLoreEntryRequest,
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
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

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

    def _write_ancestor_lore(self, folder: Path, node_id: str, tags: list[str]) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            folder / "lore" / f"{node_id}.md",
            {"id": node_id, "title": node_id, "entry_type": "lore:character", "metadata": {"tags": tags}},
            "Body.",
        )

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

    def test_saving_does_not_copy_ancestor_tags_into_the_project(self) -> None:
        # THE regression test for #339's implementation hazard. Every registry
        # writer reads merged and rewrites a whole file; hand one the merged map
        # and the next ordinary lore save silently absorbs the world's whole
        # vocabulary into this book's tags.yaml.
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Honor", entry_type="lore:character"))

        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Honor",
                body="A captain.",
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"tags": ["grayson"]},
            ),
        )

        self.assertEqual([tag["name"] for tag in self._raw_tags(self.root)], ["grayson"])
        self.assertEqual([tag["name"] for tag in self._raw_tags(self.universe)], ["treecat"])

    def test_reusing_an_inherited_tag_writes_only_the_local_assertion(self) -> None:
        # The tag is known (merged), so it is not re-registered as new; the
        # broadening it triggers is recorded HERE as this layer's assertion, and
        # the ancestor's record is not touched. Union is associative, so the
        # merged read still reports the broadened scope.
        self._write_layer_tags(self.universe, [{"name": "naval", "scope": _scope("lore", "lore:character")}])
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Basilisk", entry_type="lore:location"))

        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Basilisk",
                body="A station.",
                base_revision=entry.revision,
                entry_type="lore:location",
                metadata={"tags": ["naval"]},
            ),
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

    def test_saving_adopts_the_ancestors_casing_for_an_inherited_tag(self) -> None:
        # The bug this issue was filed for: an inherited tag used to be unknown
        # here, so it was registered as new and the author's casing forked the
        # vocabulary. Layering the read fixes it at the same call site.
        self._write_layer_tags(self.universe, [{"name": "Treecat", "scope": {}}])
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Nimitz",
                body="A treecat.",
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"tags": ["treecat"]},
            ),
        )

        self.assertEqual(saved.metadata["tags"], ["Treecat"])

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

    def test_merging_a_source_used_in_ancestor_documents_is_refused(self) -> None:
        # No ancestor *record*, but an ancestor *document* carries it — which
        # this merge cannot rewrite. Allowing it would leave the merged-away tag
        # in the (layered) usage count with no registry record anywhere, to be
        # re-registered as new by the next save touching that entry.
        self._write_layer_tags(self.root, [{"name": "sorcery", "scope": {}}, {"name": "magic", "scope": {}}])
        self._write_ancestor_lore(self.universe, "old-entry", ["sorcery"])

        with self.assertRaisesRegex(ProjectServiceError, "used in a parent folder"):
            self.service.merge_tags(MergeTagsRequest(sources=["sorcery"], target="magic"))

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

    def test_usage_counts_span_the_layer_chain(self) -> None:
        # A merged registry counted over one layer's documents is a half-layered
        # read: it looks right and reports every inherited tag as less used than
        # it is.
        self._write_layer_tags(self.universe, [{"name": "treecat", "scope": {}}])
        self._write_ancestor_lore(self.universe, "nimitz", ["treecat"])
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Samantha", entry_type="lore:character"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Samantha",
                body="Another treecat.",
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"tags": ["treecat"]},
            ),
        )

        usage = next(usage for usage in self.service.read_tags_overview().tags if usage.name == "treecat")

        self.assertEqual(usage.count, 2)


if __name__ == "__main__":
    unittest.main()
