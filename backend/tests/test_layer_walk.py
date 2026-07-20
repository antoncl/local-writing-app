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

from app.services.project.node_index import IndexLayer, NodeIndex
from app.services.project_service import ProjectService


class LayerWalkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
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

    def test_walk_runs_outermost_to_root(self) -> None:
        layers = self.service.collect_layers(self.root)

        self.assertEqual(
            [layer.folder for layer in layers],
            [self.base, self.universe, self.series, self.root],
        )

    def test_rank_is_explicit_and_matches_walk_order(self) -> None:
        # The whole point of #329: rank is stamped by the walk, not inferred by
        # a consumer from enumerate or dict insertion order.
        layers = self.service.collect_layers(self.root)

        self.assertEqual([layer.rank for layer in layers], list(range(len(layers))))

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
        # metadata.schema.yaml.
        layers = self.service.collect_layers(self.root)

        self.assertTrue(all(not layer.is_machine for layer in layers))

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
        self.assertIsNone(self.service.layer_by_id(self.root, "not-a-layer"))

    def test_visitor_sees_every_layer_in_order(self) -> None:
        class Collector:
            def __init__(self) -> None:
                self.seen: list[IndexLayer] = []

            def visit_layer(self, layer: IndexLayer) -> None:
                self.seen.append(layer)

        collector = Collector()
        self.service.visit_layers(collector, self.root)

        self.assertEqual(collector.seen, self.service.collect_layers(self.root))

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
    """

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
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
        # Base-folder assistant sorts before the book's, because the walk ranks
        # the base folder first — regardless of what order the index happens to
        # hand the entries over in.
        self._write_assistant(self.base, "outer", "Zed From Base")
        self._write_assistant(self.root, "inner", "Alpha From Book")

        natural = [entry.id for entry in self.service.list_assistant_entries().entries]
        self.assertEqual(natural, ["outer", "inner"])

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
        # The sharp edge of the old first-seen-ordinal rank, and the case the
        # walk actually changes today (not just under #307).
        #
        # `index.by_id[id] = entry` on a cross-layer shadow overwrites the value
        # but KEEPS the ancestor's insertion slot. So the descendant layer was
        # first seen at the ancestor's position, and its whole bucket teleported
        # up the roster. Here the book shadows a base-folder id, which used to
        # hoist the book's other assistants above the intermediate layer's:
        #
        #   before: base, [book bucket], middle
        #   after:  base, middle, [book bucket]
        #
        # (Within the book bucket "Collides (book)" precedes "From Book"
        # alphabetically, since neither layer has an .order.yaml.)
        #
        # Layer order must win regardless of which ids collide — this is
        # user-visible, since roster[0] is the default assistant (ADR-0024).
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

        self.assertEqual(roster, ["from-base", "from-middle", "collides", "from-book"])
        # Verified against origin/master, which yields
        # ['collides', 'from-book', 'from-base', 'from-middle'] — the whole Book
        # layer hoisted to the front, flipping roster[0] and with it the
        # default assistant.

    def test_rank_map_covers_every_layer_including_ones_without_assistants(self) -> None:
        # Ranks come from the walk, so a layer contributing no assistants still
        # occupies its position — the roster's ordering cannot depend on which
        # layers happen to have entries.
        self._write_assistant(self.root, "only", "Only One")

        _paths, ranks = self.service._assistant_layer_paths_and_ranks()
        layers = self.service.collect_layers(self.root, include_machine=True)

        self.assertEqual(len(ranks), len(layers))
        self.assertEqual(sorted(ranks.values()), list(range(len(layers))))
        root_layer = next(layer for layer in layers if layer.is_root)
        self.assertGreater(root_layer.rank, 0)


class MachineLayerIsAnOrdinaryLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        # Redirect the machine config dir into the temp tree so the machine
        # layer is deterministic rather than "whatever this box happens to have".
        self.config_dir = Path(self.temp_dir.name) / "config"
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

        self.assertEqual(
            [layer.folder for layer in without],
            [layer.folder for layer in with_machine if not layer.is_machine],
        )

    def test_machine_layer_has_one_constructor(self) -> None:
        # The walk and the two no-project-chain callers must agree on the
        # machine layer's identity — they used to build it separately.
        (self.config_dir / "assistants").mkdir()

        from_walk = self.service.collect_layers(self.root, include_machine=True)[0]
        standalone = self.service.machine_layer()

        self.assertEqual(from_walk, standalone)


if __name__ == "__main__":
    unittest.main()
