"""The one layer walk (#329).

Pins the contract every consumer now depends on: order, explicit rank, the
`is_root` / `is_machine` flags and the label rules. Before #329 each consumer
re-derived this, so a change to "how far do we walk" was six edits; these tests
exist so the next change to the walk is caught in one place.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.models import ReorderAssistantsRequest, UnlistAssistantRequest
from app.services.project.assistants import AssistantsOrder
from app.services.project.node_index import IndexLayer, NodeIndex
from app.services.project_service import ProjectService


class LayerWalkTests(unittest.TestCase):
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
        # A REAL machine layer. conftest's autouse fixture points the config dir
        # at an empty tmp path, so without this `machine_layer()` returns None
        # and every "the machine layer is excluded" assertion below passes for
        # the wrong reason — it was vacuous until this existed.
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        (self.config_dir / "assistants").mkdir()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_walk_runs_outermost_to_root(self) -> None:
        layers = self.service.collect_layers(self.root)

        self.assertEqual(
            [layer.folder for layer in layers],
            [self.base, self.universe, self.series, self.root],
        )

    def test_rank_is_explicit_and_matches_walk_order(self) -> None:
        # The whole point of #329: rank is stamped by the walk, not inferred by
        # a consumer from enumerate or dict insertion order. Asserted against
        # the known fixture, not `range(len(layers))` — the latter also holds
        # for a truncated or empty walk.
        layers = self.service.collect_layers(self.root)

        self.assertEqual(
            [(layer.folder.name, layer.rank) for layer in layers],
            [("writing", 0), ("honorverse", 1), ("honor-harrington", 2), ("book01", 3)],
        )

    def test_walk_canonicalises_the_root_it_is_given(self) -> None:
        """#356: the walk must compare paths in ONE normal form.

        It used to certify the walk with `_is_relative_to` — which resolves both
        operands — and then walk an unresolved `current` against a resolved
        `base_folder`. Any path whose `.resolve()` differs from its literal form
        (a junction or symlink above the project, a mapped or substituted drive,
        an 8.3 short path) made that equality unreachable, and the walk ran up to
        the drive root, where `parent` is a fixpoint — forever.

        A `..` segment reproduces the mismatch on every platform. Deliberately
        an assertion about the RESULT rather than a hang: a regression test that
        wedges the suite is worse than the bug.
        """
        via_dotdot = self.series / self.root.name / ".." / self.root.name

        layers = self.service.collect_layers(via_dotdot)

        self.assertEqual(
            [layer.folder for layer in layers],
            [self.base, self.universe, self.series, self.root],
        )

    def test_is_root_marks_only_the_open_project(self) -> None:
        layers = self.service.collect_layers(self.root)

        self.assertEqual([layer.is_root for layer in layers], [False, False, False, True])

    def test_labels_follow_the_layer_rules(self) -> None:
        # Outermost project layer is "Base Folder", the open project takes the
        # project title, everything between is the folder name.
        layers = self.service.collect_layers(self.root)

        self.assertEqual(
            [layer.label for layer in layers],
            ["Base Folder", "honorverse", "honor-harrington", "Book 1"],
        )

    def test_machine_layer_is_excluded_by_default(self) -> None:
        # Schema layering must not see it — it is out-of-tree and carries no
        # metadata.schema.yaml. setUp creates a real machine assistants/ dir, so
        # this fails if `include_machine` ever defaults to True.
        self.assertIsNotNone(self.service.machine_layer(), "fixture must have a machine layer")

        layers = self.service.collect_layers(self.root)

        self.assertTrue(all(not layer.is_machine for layer in layers))
        self.assertEqual(len(layers), 4)
        # And the schema surfaces built on the walk must not pick it up either.
        machine_folder = self.service.machine_layer().folder
        self.assertNotIn(
            machine_folder / "metadata.schema.yaml",
            self.service._metadata_schema_layer_paths(self.root),
        )
        self.assertNotIn(
            str(machine_folder),
            [layer.folder_path for layer in self.service.read_metadata_schema_layers().layers],
        )

    def test_schema_layer_paths_come_from_the_walk(self) -> None:
        paths = self.service._metadata_schema_layer_paths(self.root)

        self.assertEqual(
            paths,
            [folder / "metadata.schema.yaml" for folder in (self.base, self.universe, self.series, self.root)],
        )

    def test_layer_ids_are_unique_and_reversible(self) -> None:
        layers = self.service.collect_layers(self.root)
        ids = [layer.id for layer in layers]

        self.assertEqual(len(set(ids)), len(ids))
        for layer in layers:
            self.assertEqual(self.service.layer_by_id(self.root, layer.id), layer)

    def test_layer_by_id_returns_none_for_an_unknown_id(self) -> None:
        # Paired with a positive lookup, so an empty walk (which would make the
        # None assertion pass trivially) fails here.
        self.assertIsNone(self.service.layer_by_id(self.root, "not-a-layer"))
        expected = self.service._metadata_schema_layer_id(self.universe)
        found = self.service.layer_by_id(self.root, expected)
        self.assertIsNotNone(found)
        self.assertEqual(found.folder, self.universe)

    def test_visitor_sees_every_layer_in_order(self) -> None:
        class Collector:
            def __init__(self) -> None:
                self.seen: list[IndexLayer] = []

            def visit_layer(self, layer: IndexLayer) -> None:
                self.seen.append(layer)

        collector = Collector()
        self.service.visit_layers(collector, self.root)

        # Compared against an explicit oracle, not against `collect_layers` —
        # that is itself LayerCollector over visit_layers, so the two agreeing
        # proved nothing (they agreed at [] == [] too).
        self.assertEqual(
            [layer.folder for layer in collector.seen],
            [self.base, self.universe, self.series, self.root],
        )

    def test_walk_degrades_to_the_project_alone_without_a_base_folder(self) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest["settings"].pop("projects_base_folder")
        self.service._write_yaml(self.root / "project.yaml", manifest)

        layers = self.service.collect_layers(self.root)

        self.assertEqual([layer.folder for layer in layers], [self.root])
        self.assertTrue(layers[0].is_root)
        self.assertEqual(layers[0].rank, 0)


class AssistantRankComesFromTheWalkTests(unittest.TestCase):
    """#329's actual bug fix — user-visible, since topmost is the default
    assistant under ADR-0024.

    The roster took each layer's rank from `index.by_id` insertion order, which
    misordered it two ways:

    * **Today.** A cross-layer id collision reuses the *ancestor's* dict slot
      (`by_id[id] = entry` replaces the value, keeps the position), so a
      descendant that shadows an outer id was "first seen" at the outer layer's
      position and its whole bucket jumped up the roster.
    * **Later.** An incremental index patch (#307) re-parsing one file would
      move its layer to the end.

    Assistants were the only order-sensitive consumer: lore, prompts, mutation
    sets and views all sort explicitly by `(title, id)`.

    ⚠ **#332 rewrote what these assert.** Layer rank is no longer a sort term at
    all: every layer's `.order.yaml` folds into one merged sequence, and position
    in *that* is the whole ordering story — so the roster is now most-local-first,
    the inverse of what #329 shipped. The invariant worth keeping is the one
    below the expectations: the roster must not depend on index insertion order.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_assistant(self, layer_folder: Path, entry_id: str, title: str) -> None:
        (layer_folder / "assistants").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            layer_folder / "assistants" / f"{entry_id}.md",
            entry_id,
            title,
            "assistant",
            {},
            "",
        )

    def test_roster_order_survives_reversed_index_insertion_order(self) -> None:
        # The base folder's assistant is titled to win alphabetically and the
        # book's to lose it, then both are *listed* in their own layer's order
        # file — so the assertion below is driven by merged position, not by
        # title, and stays a real test of the ordering path rather than of
        # `sorted()`.
        self._write_assistant(self.base, "outer", "Alpha From Base")
        self._write_assistant(self.root, "inner", "Zed From Book")
        self.service._write_assistants_order(
            self.base / "assistants", AssistantsOrder(ids=["outer"])
        )
        self.service._write_assistants_order(
            self.root / "assistants", AssistantsOrder(ids=["inner"])
        )

        # Most-local-first since #332: the book's list leads, the base folder's
        # remainder follows. Pre-#332 this was ["outer", "inner"] because layer
        # rank led the sort key.
        natural = [entry.id for entry in self.service.list_assistant_entries().entries]
        self.assertEqual(natural, ["inner", "outer"])

        # Now hand the roster an index whose insertion order is reversed. Under
        # the old first-seen-ordinal rank this flipped the roster; under the
        # walk's explicit rank it must not.
        real_index = self.service._build_assistant_index()
        reversed_index = NodeIndex()
        for entry_id in reversed(list(real_index.by_id)):
            reversed_index.by_id[entry_id] = real_index.by_id[entry_id]

        original_builder = self.service._build_assistant_index
        self.service._build_assistant_index = lambda: reversed_index  # type: ignore[method-assign]
        try:
            perturbed = [entry.id for entry in self.service.list_assistant_entries().entries]
        finally:
            self.service._build_assistant_index = original_builder  # type: ignore[method-assign]

        self.assertEqual(perturbed, natural)

    def test_a_shadowed_assistant_id_does_not_drag_its_layer_up_the_roster(self) -> None:
        # The sharp edge of the old first-seen-ordinal rank. `index.by_id[id] =
        # entry` on a cross-layer shadow overwrites the value but KEEPS the
        # ancestor's insertion slot, so the descendant layer was first seen at
        # the ancestor's position and its whole bucket teleported up the roster.
        #
        # #332 removed the layer term the bug expressed itself through, so the
        # shadow can no longer move anything: with no `.order.yaml` anywhere,
        # every assistant is unlisted and the roster is one global alphabetical
        # tail. That is a weaker guarantee than #329's — the ordering-sensitive
        # version of this case now lives in `AssistantOrderMergeTests` — but it
        # still pins the property that a collision does not reorder the roster.
        #
        # User-visible either way, since roster[0] is the default assistant
        # (ADR-0024).
        middle = self.base / "middle"
        book = middle / "book"
        service = ProjectService()
        service.create_project(book, "Book")
        manifest = service._read_yaml(book / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        service._write_yaml(book / "project.yaml", manifest)

        def write(folder: Path, entry_id: str, title: str) -> None:
            (folder / "assistants").mkdir(parents=True, exist_ok=True)
            service._write_node_entry_file(
                folder / "assistants" / f"{entry_id}.md", entry_id, title, "assistant", {}, ""
            )

        write(self.base, "from-base", "From Base")
        write(middle, "from-middle", "From Middle")
        write(book, "from-book", "From Book")
        write(self.base, "collides", "Collides (base)")
        write(book, "collides", "Collides (book)")

        # conftest's autouse fixture isolates the machine config dir, so the
        # roster here is exactly the three project layers.
        roster = [entry.id for entry in service.list_assistant_entries().entries]

        # "Collides (book)" wins the id, so the base's copy is not in the roster
        # at all; the rest is title order.
        self.assertEqual(roster, ["collides", "from-base", "from-book", "from-middle"])

    def test_a_layer_with_no_assistants_folder_does_not_break_the_merge(self) -> None:
        # The fold visits every layer, including ones that contribute nothing.
        # A missing `assistants/` folder must read as "no opinion" rather than
        # ending the walk or raising — the roster's ordering cannot depend on
        # which layers happen to have entries.
        self._write_assistant(self.base, "outer", "Outer")
        self._write_assistant(self.root, "inner", "Inner")
        self.service._write_assistants_order(
            self.root / "assistants", AssistantsOrder(ids=["inner", "outer"])
        )
        # `middle` sits between base and root with no assistants/ folder at all.
        (self.base / "middle").mkdir(parents=True, exist_ok=True)

        roster = [entry.id for entry in self.service.list_assistant_entries().entries]
        self.assertEqual(roster, ["inner", "outer"])


class AssistantOrderMergeTests(unittest.TestCase):
    """#332: every layer's `.order.yaml` folds into ONE priority sequence,

        merged = local.ids + (inherited_merged − local.ids) − local.excluded

    applied outermost → innermost. Descendant-wins has to fall out in *both*
    directions or the shape is wrong, so both directions are pinned below.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_assistant(self, layer_folder: Path, entry_id: str, title: str) -> None:
        (layer_folder / "assistants").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            layer_folder / "assistants" / f"{entry_id}.md", entry_id, title, "assistant", {}, ""
        )

    def _order(self, layer_folder: Path, **kwargs) -> None:
        self.service._write_assistants_order(
            layer_folder / "assistants", AssistantsOrder(**kwargs)
        )

    def _roster(self) -> list[str]:
        return [entry.id for entry in self.service.list_assistant_entries().entries]

    def test_local_list_leads_and_inherited_remainder_follows(self) -> None:
        self._write_assistant(self.base, "outer_a", "Outer A")
        self._write_assistant(self.base, "outer_b", "Outer B")
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.base, ids=["outer_a", "outer_b"])
        self._order(self.root, ids=["inner"])

        self.assertEqual(self._roster(), ["inner", "outer_a", "outer_b"])

    def test_naming_an_inherited_id_locally_raises_it_to_the_local_position(self) -> None:
        # The id is stripped from the inherited remainder before concatenation,
        # so it rises rather than appearing twice.
        self._write_assistant(self.base, "outer_a", "Outer A")
        self._write_assistant(self.base, "outer_b", "Outer B")
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.base, ids=["outer_a", "outer_b"])
        self._order(self.root, ids=["outer_b", "inner"])

        self.assertEqual(self._roster(), ["outer_b", "inner", "outer_a"])

    def test_descendant_exclusion_removes_an_inherited_assistant(self) -> None:
        self._write_assistant(self.base, "outer", "Outer")
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.base, ids=["outer"])
        self._order(self.root, ids=["inner"], excluded=["outer"])

        self.assertEqual(self._roster(), ["inner"])

    def test_a_descendant_can_undo_an_ancestors_exclusion(self) -> None:
        # The other direction of descendant-wins: an ancestor's `excluded` is
        # not binding on a layer that positively lists the id. Needs three
        # layers — the exclusion has to be inherited, not local.
        middle = self.base / "middle"
        book = middle / "book"
        service = ProjectService()
        service.create_project(book, "Book")
        manifest = service._read_yaml(book / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        service._write_yaml(book / "project.yaml", manifest)

        for folder, entry_id, title in (
            (self.base, "outer", "Outer"),
            (book, "inner", "Inner"),
        ):
            (folder / "assistants").mkdir(parents=True, exist_ok=True)
            service._write_node_entry_file(
                folder / "assistants" / f"{entry_id}.md", entry_id, title, "assistant", {}, ""
            )
        service._write_assistants_order(
            self.base / "assistants", AssistantsOrder(ids=["outer"])
        )
        service._write_assistants_order(
            middle / "assistants", AssistantsOrder(excluded=["outer"])
        )
        service._write_assistants_order(
            book / "assistants", AssistantsOrder(ids=["outer", "inner"])
        )

        roster = [entry.id for entry in service.list_assistant_entries().entries]
        self.assertEqual(roster, ["outer", "inner"])

    def test_ids_wins_when_one_layer_both_lists_and_excludes_an_id(self) -> None:
        # Malformed, reachable only by hand-editing. Files are truth, so it must
        # not break the roster — `ids` wins, and we log it.
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.root, ids=["inner"], excluded=["inner"])

        with self.assertLogs("app.services.project.assistants", level="WARNING") as logged:
            self.assertEqual(self._roster(), ["inner"])
        self.assertIn("inner", logged.output[0])

    def test_a_duplicated_id_in_one_layers_list_keeps_its_first_position(self) -> None:
        # Hand-editable file, so the duplicate has to resolve to something. It
        # takes its first position and does not displace what follows.
        self._write_assistant(self.root, "a1", "A One")
        self._write_assistant(self.root, "a2", "A Two")
        self._order(self.root, ids=["a1", "a2", "a1"])

        self.assertEqual(
            self.service.merged_assistant_order().ids, ["a1", "a2"]
        )
        self.assertEqual(self._roster(), ["a1", "a2"])

    def test_ids_naming_a_nonexistent_assistant_are_ignored(self) -> None:
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.root, ids=["ghost", "inner"], excluded=["also_gone"])

        self.assertEqual(self._roster(), ["inner"])

    def test_reorder_accepts_an_inherited_id_and_writes_it_locally(self) -> None:
        # THE gesture #332 exists for, and the one the pre-#332 validation
        # rejected with a 422: dragging an inherited assistant names a foreign
        # id in the LOCAL file. The ancestor's file must not be touched —
        # that is what makes the drag layer-safe by construction rather than by
        # the UI remembering not to do it.
        self._write_assistant(self.base, "outer", "Outer")
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.base, ids=["outer"])
        base_order_before = (self.base / "assistants" / ".order.yaml").read_text(
            encoding="utf-8"
        )
        # The book layer owns assistants of its own here. The folder-less case
        # is the one the pre-#332 404 guard broke, so it gets its own test.

        self.service.reorder_assistant_entries(
            ReorderAssistantsRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                ordered_ids=["outer", "inner"],
            )
        )

        self.assertEqual(self._roster(), ["outer", "inner"])
        self.assertEqual(
            self.service._read_assistants_order(self.root / "assistants").ids,
            ["outer", "inner"],
        )
        self.assertEqual(
            (self.base / "assistants" / ".order.yaml").read_text(encoding="utf-8"),
            base_order_before,
        )

    def test_a_layer_owning_no_assistants_can_still_reorder_inherited_ones(self) -> None:
        # A book that has written no assistants of its own has no `assistants/`
        # folder, and the pre-#332 guard 404'd there — rejecting the drag at
        # precisely the layer most likely to want it. The order file (and its
        # folder) are created on demand.
        self._write_assistant(self.base, "outer_a", "Outer A")
        self._write_assistant(self.base, "outer_b", "Outer B")
        self.assertFalse((self.root / "assistants").exists())

        self.service.reorder_assistant_entries(
            ReorderAssistantsRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                ordered_ids=["outer_b", "outer_a"],
            )
        )

        self.assertEqual(self._roster(), ["outer_b", "outer_a"])
        self.assertTrue((self.root / "assistants" / ".order.yaml").exists())

    def test_unlisting_an_inherited_assistant_does_not_touch_the_ancestor(self) -> None:
        self._write_assistant(self.base, "outer", "Outer")
        self._write_assistant(self.root, "inner", "Inner")
        self._order(self.base, ids=["outer"])

        self.service.unlist_assistant_entry(
            UnlistAssistantRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                entry_id="outer",
            )
        )

        self.assertEqual(self._roster(), ["inner"])
        self.assertEqual(
            self.service._read_assistants_order(self.base / "assistants").ids, ["outer"]
        )
        self.assertEqual(
            self.service._read_assistants_order(self.base / "assistants").excluded, []
        )
        self.assertTrue((self.base / "assistants" / "outer.md").exists())

    def test_unlisted_assistants_trail_in_one_global_alphabetical_tail(self) -> None:
        # Pre-#332 this tail was per layer, because rank led the sort key.
        self._write_assistant(self.base, "outer", "Beta From Base")
        self._write_assistant(self.root, "inner", "Alpha From Book")
        self._write_assistant(self.root, "listed", "Zed But Listed")
        self._order(self.root, ids=["listed"])

        self.assertEqual(self._roster(), ["listed", "inner", "outer"])


class MachineLayerIsAnOrdinaryLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        # Redirect the machine config dir into the temp tree so the machine
        # layer is deterministic rather than "whatever this box happens to have".
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_machine_layer_leads_the_walk(self) -> None:
        (self.config_dir / "assistants").mkdir()

        layers = self.service.collect_layers(self.root, include_machine=True)

        # Machine first (rank 0) is what keeps the roster layer-grouped with the
        # Machine bucket on top (ADR-0037 §7 / #224).
        self.assertTrue(layers[0].is_machine)
        self.assertEqual(layers[0].rank, 0)
        self.assertEqual(layers[0].label, "Machine")
        self.assertFalse(layers[0].is_root)
        self.assertEqual([layer.rank for layer in layers], list(range(len(layers))))

    def test_machine_layer_is_omitted_when_it_has_no_assistants_folder(self) -> None:
        # Matches the early return the old `_collect_machine_layer_assistants`
        # made before #329 folded it into the walk.
        self.assertFalse((self.config_dir / "assistants").exists())

        layers = self.service.collect_layers(self.root, include_machine=True)

        self.assertTrue(all(not layer.is_machine for layer in layers))
        self.assertEqual([layer.rank for layer in layers], list(range(len(layers))))

    def test_project_layers_are_unaffected_by_the_machine_flag(self) -> None:
        (self.config_dir / "assistants").mkdir()

        without = self.service.collect_layers(self.root)
        with_machine = self.service.collect_layers(self.root, include_machine=True)

        # Positive assertions on both sides. Filtering the machine layer out of
        # one side and comparing was vacuous — it held even when the walk
        # returned nothing at all.
        self.assertEqual([layer.folder for layer in without], [self.base, self.root])
        self.assertEqual(
            [layer.folder for layer in with_machine],
            [self.config_dir, self.base, self.root],
        )
        self.assertEqual([layer.is_machine for layer in with_machine], [True, False, False])

    def test_machine_layer_has_one_constructor(self) -> None:
        # The walk and the no-project-chain callers must agree on the machine
        # layer's IDENTITY — they used to build it separately. Compare the
        # identity fields explicitly rather than the whole record: `rank` is
        # positional and would make this fail spuriously if the machine layer
        # ever stopped leading the walk, which is #332's business, not this
        # test's.
        (self.config_dir / "assistants").mkdir()

        from_walk = next(
            layer
            for layer in self.service.collect_layers(self.root, include_machine=True)
            if layer.is_machine
        )
        standalone = self.service.machine_layer()

        self.assertIsNotNone(standalone)
        self.assertEqual(
            (from_walk.folder, from_walk.id, from_walk.label, from_walk.is_machine, from_walk.is_root),
            (standalone.folder, standalone.id, standalone.label, standalone.is_machine, standalone.is_root),
        )
        self.assertEqual(standalone.folder, self.config_dir)


class PerLayerCollectionRulesTests(unittest.TestCase):
    """`_NodeIndexBuilder` / `_families_for_layer` — the per-layer decisions the
    index walk used to inline.

    Both rules below were unpinned by the whole 799-test suite: deleting the
    machine-layer branch, or collecting chats at every layer, left every test
    green. They are new code in #329, so they get their own net.
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_chat(self, layer_folder: Path, chat_id: str) -> None:
        (layer_folder / "chats").mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(
            layer_folder / "chats" / f"{chat_id}.yaml",
            {"id": chat_id, "title": f"Chat {chat_id}", "messages": []},
        )

    def test_machine_layer_contributes_assistants_only(self) -> None:
        # It is out-of-tree and holds the user's roster. Lore (or any other
        # family) sitting next to it must not enter the index.
        (self.config_dir / "assistants").mkdir()
        self.service._write_node_entry_file(
            self.config_dir / "assistants" / "m1.md", "m1", "Machine One", "assistant", {}, ""
        )
        (self.config_dir / "lore").mkdir()
        self.service._write_node_entry_file(
            self.config_dir / "lore" / "stray.md", "stray-lore", "Stray", "lore", {}, ""
        )

        index = self.service._build_node_index(self.root)

        self.assertIn("m1", index.by_id)
        self.assertNotIn("stray-lore", index.by_id)

    def test_chats_are_collected_only_at_the_open_project(self) -> None:
        # Chats are book-scoped like scenes; an ancestor's chats/ must be
        # ignored even though the ancestor is a layer of this project.
        self._write_chat(self.base, "chat_ancestor")
        self._write_chat(self.root, "chat_book")

        index = self.service._build_node_index(self.root)

        self.assertIn("chat_book", index.by_id)
        self.assertNotIn("chat_ancestor", index.by_id)

    def test_scenes_are_collected_only_at_the_open_project(self) -> None:
        # The other half of the same rule, and the one `_families_for_layer`
        # expresses as `family.kind != "scene" or layer.is_root`.
        (self.base / "scenes").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.base / "scenes" / "ancestor.md", "scene-ancestor", "Ancestor Scene", "scene", {}, ""
        )

        index = self.service._build_node_index(self.root)

        self.assertNotIn("scene-ancestor", index.by_id)
        # The project's own seeded scene IS indexed — so this fails if the walk
        # collapsed to nothing rather than because the rule works.
        self.assertTrue(any(entry.kind == "scene" for entry in index.by_id.values()))

    def test_ancestor_lore_is_collected(self) -> None:
        # Guards the inverse of the two rules above: the scene/chat restriction
        # must not be over-applied to cross-layer families.
        (self.base / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.base / "lore" / "shared.md", "ancestor-lore", "Ancestor Lore", "lore", {}, ""
        )

        index = self.service._build_node_index(self.root)

        self.assertIn("ancestor-lore", index.by_id)


if __name__ == "__main__":
    unittest.main()
