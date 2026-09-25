"""Migration v14 (ADR-0095 §12): legacy inline mutation markers become
`mutation_set` nodes + anchors, per layer, outermost first.

Most fixtures are v13 layers written by hand — node files already carry their
placement (ADR-0094), the way `test_migration_levels.py`'s do — and
`migrate_layer_mutation_anchors` is called directly, the fast unit-test path
every other chain step's own test file uses. The cross-layer entity-type test
and the resolved-value test go through a real two-layer project and
`ProjectService.opened_at`, because they need the live schema/index, not just
the migration module.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from layer_fixtures import declare

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    MetadataFieldDefinition,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.services.migrations import CURRENT_VERSION, ChainContext, read_project_version
from app.services.migrations_mutation_anchors import (
    _convert_scenes,
    _match_placed_sets,
    _mint_row_ids,
    _scene_paths_by_id,
    _seed_entity_types,
    migrate_layer_mutation_anchors,
)
from app.services.project.mutation_anchors import derive_anchor_id, derive_set_id
from app.services.project_service import ProjectService

# ----- raw-file fixture helpers (independent of the migration's own IO) -----


# `write_bytes`, never `write_text`: on Windows, `Path.write_text`'s default
# `newline=None` translates every `\n` to `\r\n`, which would silently give
# every fixture CRLF front matter the migration's `\n`-only split never sees
# in a real (app-written) file — `test_migration_levels.py`'s own `_write_node`
# avoids the same trap the same way.


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    _write_text(path, yaml.safe_dump(data, sort_keys=False))


def _split(text: str) -> tuple[str, str]:
    _, rest = text.split("---\n", 1)
    front, body = rest.split("\n---\n", 1)
    return front, body.lstrip("\n")


def _read(path: Path) -> tuple[dict[str, Any], str]:
    front, body = _split(path.read_bytes().decode("utf-8"))
    return yaml.safe_load(front) or {}, body


def _write_scene(folder: Path, scene_id: str, body: str, *, parent: str | None = None, rank: int = 1) -> Path:
    front: dict[str, Any] = {"id": scene_id, "title": scene_id, "entry_type": "manuscript:scene"}
    if parent is not None:
        front["parent"] = parent
    front["rank"] = rank
    path = folder / f"{scene_id}.md"
    _write_text(path, "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n" + body)
    return path


def _write_lore(folder: Path, entry_id: str, title: str, *, entry_type: str = "lore:character") -> Path:
    front = {"id": entry_id, "title": title, "entry_type": entry_type, "metadata": {}}
    path = folder / f"{entry_id}.md"
    _write_text(path, "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n")
    return path


def _write_set(folder: Path, set_id: str, front_extra: dict[str, Any]) -> Path:
    front: dict[str, Any] = {"id": set_id, "title": "", "entry_type": "mutation_set:mutation_set"}
    front.update(front_extra)
    path = folder / f"{set_id}.md"
    _write_text(path, "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n")
    return path


def _write_override(folder: Path, entity_id: str, rows: list[dict[str, Any]]) -> Path:
    front = {"entity_id": entity_id, "entry_type": "override:override", "rows": rows}
    path = folder / f"{entity_id}.md"
    _write_text(path, "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n")
    return path


class _FlatLayerTests(unittest.TestCase):
    """Fixtures: a single v13 layer, no schema needed — the migration itself
    never validates rows (ADR §4)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.root.mkdir(parents=True)
        _write_yaml(self.root / "project.yaml", {"title": "Book", "schema_version": 13})
        _write_lore(self.root / "lore", "honor", "Honor")
        _write_lore(self.root / "lore", "mira", "Mira")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _migrate(self, ctx: ChainContext | None = None) -> ChainContext:
        ctx = ctx or ChainContext()
        migrate_layer_mutation_anchors(self.root, ctx)
        return ctx

    def _set_path(self, set_id: str) -> Path:
        return self.root / "mutation-sets" / f"{set_id}.md"

    # ---- markers become sets + anchors -------------------------------------

    def test_single_line_marker_becomes_set_and_anchor(self) -> None:
        body = "Before. <!-- mutate:entity=honor;field=rank;value=Captain;name=Promotion;id=m1 --> After."
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()

        _, new_body = _read(self.root / "scenes" / "s1.md")
        self.assertIn("mutate:set=", new_body)
        self.assertNotIn("mutate:entity=", new_body)
        set_id = derive_set_id("m1")
        set_front, _ = _read(self._set_path(set_id))
        self.assertEqual(set_front["id"], set_id)
        self.assertEqual(set_front["title"], "Promotion")
        self.assertEqual(set_front["entry_type"], "mutation_set:mutation_set")
        self.assertEqual(set_front["target_entry_type"], "lore:character")
        self.assertEqual(set_front["metadata"], {"target_entity": "honor"})
        self.assertEqual(set_front["rows"], [{"id": "m1", "field": "rank", "op": "replace", "value": "Captain"}])

    def test_carrier_becomes_one_set_rows_keep_ids(self) -> None:
        carrier = (
            "<!-- mutate:entity=honor;name=Promotion;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=posting;value=Bridge;id=r2\n"
            "-->"
        )
        _write_scene(self.root / "scenes", "s1", f"Text. {carrier} more.")

        self._migrate()

        set_id = derive_set_id("u1")
        set_front, _ = _read(self._set_path(set_id))
        self.assertEqual([row["id"] for row in set_front["rows"]], ["r1", "r2"])
        self.assertEqual([row["field"] for row in set_front["rows"]], ["rank", "posting"])

    def test_group_markers_become_separate_sets_with_the_group_title(self) -> None:
        body = (
            "<!-- mutate:entity=honor;field=rank;value=Captain;name=Storm;group=g1;id=m1 --> "
            "middle "
            "<!-- mutate:entity=honor;field=posting;value=Bridge;name=Storm;group=g1;id=m2 -->"
        )
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()

        for unit_id in ("m1", "m2"):
            set_front, _ = _read(self._set_path(derive_set_id(unit_id)))
            self.assertEqual(set_front["title"], "Storm")
            self.assertEqual(len(set_front["rows"]), 1)
        self.assertNotEqual(derive_set_id("m1"), derive_set_id("m2"))

    def test_group_close_expands_to_a_close_per_member_anchor(self) -> None:
        body = (
            "<!-- mutate:entity=honor;field=rank;value=Captain;group=g1;id=m1 -->"
            "<!-- mutate:entity=honor;field=posting;value=Bridge;group=g1;id=m2 -->"
            "<!-- mutate:close;ref=g1;id=c1 -->"
        )
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()

        _, new_body = _read(self.root / "scenes" / "s1.md")
        self.assertIn("ref=m1", new_body)
        self.assertIn("ref=m2", new_body)
        self.assertEqual(new_body.count("mutate:close"), 2)

    def test_row_close_becomes_ref_and_row(self) -> None:
        carrier = (
            "<!-- mutate:entity=honor;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=posting;value=Bridge;id=r2\n"
            "-->"
        )
        body = f"{carrier}<!-- mutate:close;ref=r2;id=c1 -->"
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()

        _, new_body = _read(self.root / "scenes" / "s1.md")
        self.assertIn("ref=u1;row=r2;id=c1", new_body)

    def test_unit_id_repeated_across_two_scenes_gets_two_sets(self) -> None:
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        _write_scene(self.root / "scenes", "s1", marker, rank=1)
        _write_scene(self.root / "scenes", "s2", marker, rank=2)

        self._migrate()

        first_set = derive_set_id("dup")
        second_set = derive_set_id("s2:dup")
        self.assertTrue(self._set_path(first_set).exists())
        self.assertTrue(self._set_path(second_set).exists())
        _, s1_body = _read(self.root / "scenes" / "s1.md")
        _, s2_body = _read(self.root / "scenes" / "s2.md")
        self.assertIn(f"set={first_set};id=dup", s1_body)
        self.assertIn(f"set={second_set};id={derive_anchor_id('s2', 'dup')}", s2_body)

    def test_dead_entity_keeps_the_pin_and_empty_target_type(self) -> None:
        body = "<!-- mutate:entity=ghost;field=rank;value=Captain;id=m1 -->"
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()

        set_front, _ = _read(self._set_path(derive_set_id("m1")))
        self.assertEqual(set_front["metadata"], {"target_entity": "ghost"})
        self.assertNotIn("target_entry_type", set_front)

    # ---- byte preservation / idempotence / resumability --------------------

    def test_scene_front_matter_is_byte_identical_after_conversion(self) -> None:
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        path = _write_scene(self.root / "scenes", "s1", body)
        original_text = path.read_bytes().decode("utf-8")
        original_front, _ = _split(original_text)

        self._migrate()

        new_text = path.read_bytes().decode("utf-8")
        new_front, new_body = _split(new_text)
        self.assertEqual(new_front, original_front)
        self.assertNotEqual(new_body, body)

    def test_rerun_is_a_no_op_byte_identical(self) -> None:
        body = (
            "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
            "<!-- mutate:close;ref=m1;id=c1 -->"
        )
        _write_scene(self.root / "scenes", "s1", body)

        self._migrate()
        scene_path = self.root / "scenes" / "s1.md"
        set_path = self._set_path(derive_set_id("m1"))
        scene_bytes = scene_path.read_bytes()
        set_bytes = set_path.read_bytes()

        self._migrate()  # a second run over already-converted input

        self.assertEqual(scene_path.read_bytes(), scene_bytes)
        self.assertEqual(set_path.read_bytes(), set_bytes)

    def test_a_partial_run_is_completed_by_a_rerun(self) -> None:
        """Simulates a crash between "sets written" and "scenes rewritten"
        (ADR §12's own write order) — the scene body still holds the legacy
        marker, but the set file the first (partial) run wrote is untouched."""
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        scene_path = _write_scene(self.root / "scenes", "s1", body)
        set_id = derive_set_id("m1")
        _write_set(
            self.root / "mutation-sets",
            set_id,
            {"target_entry_type": "lore:character", "metadata": {"target_entity": "honor"},
             "rows": [{"id": "m1", "field": "rank", "op": "replace", "value": "Captain"}]},
        )
        # The scene body is still legacy-shaped — as if the crash happened
        # after the set write but before the scene rewrite.
        self.assertIn("mutate:entity=", scene_path.read_bytes().decode("utf-8"))

        self._migrate()

        _, new_body = _read(scene_path)
        self.assertIn("mutate:set=", new_body)
        set_front, _ = _read(self._set_path(set_id))
        self.assertEqual(set_front["rows"][0]["id"], "m1")

    # ---- row ids -------------------------------------------------------------

    def test_row_ids_are_minted_deterministically(self) -> None:
        set_id = "mutation_set_existing"
        _write_set(
            self.root / "mutation-sets",
            set_id,
            {"rows": [{"field": "rank", "op": "replace", "value": "Captain"}]},
        )

        self._migrate()

        set_front, _ = _read(self._set_path(set_id))
        self.assertTrue(set_front["rows"][0]["id"].startswith("row_"))

        # Re-run: the minted id is kept, not re-minted.
        minted_id = set_front["rows"][0]["id"]
        self._migrate()
        set_front_again, _ = _read(self._set_path(set_id))
        self.assertEqual(set_front_again["rows"][0]["id"], minted_id)

    def test_override_rows_are_never_touched(self) -> None:
        override_path = _write_override(
            self.root / "overrides", "honor", [{"field": "rank", "op": "replace", "value": "Captain"}]
        )
        original = override_path.read_bytes()

        self._migrate()

        self.assertEqual(override_path.read_bytes(), original)

    # ---- placed sets ---------------------------------------------------------

    def test_a_matched_placed_set_takes_over_and_the_placed_file_is_deleted(self) -> None:
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        _write_scene(self.root / "scenes", "s1", body)
        placed_id = "mutation_set_placed1"
        _write_set(
            self.root / "mutation-sets",
            placed_id,
            {
                "title": "Promotion",
                "placed": True,
                "target_entry_type": "lore:character",
                "metadata": {"target_entity": "honor"},
                "rows": [{"id": "row_x", "field": "rank", "op": "replace", "value": "Captain"}],
            },
        )
        chat_folder = self.root / "chats"
        _write_text(
            chat_folder / "chat1.md",
            "---\n"
            + yaml.safe_dump(
                {
                    "id": "chat1",
                    "title": "Chat",
                    "entry_type": "chat:chat_session",
                    "metadata": {"staged_set": placed_id},
                },
                sort_keys=False,
            )
            + "---\n\n",
        )

        self._migrate()

        converted_id = derive_set_id("m1")
        self.assertFalse((self.root / "mutation-sets" / f"{placed_id}.md").exists())
        converted_front, _ = _read(self._set_path(converted_id))
        self.assertEqual(converted_front["title"], "Promotion")  # inherited: the converted set had none
        self.assertNotIn("placed", converted_front)
        chat_front, _ = _read(chat_folder / "chat1.md")
        self.assertEqual(chat_front["metadata"]["staged_set"], converted_id)

    def test_an_unmatched_placed_set_is_kept_staged_placed_dropped(self) -> None:
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        _write_scene(self.root / "scenes", "s1", body)
        placed_id = "mutation_set_placed2"
        _write_set(
            self.root / "mutation-sets",
            placed_id,
            {
                "title": "Unrelated",
                "placed": True,
                "target_entry_type": "lore:character",
                "metadata": {"target_entity": "honor"},
                # Different rows: no candidate set will match this.
                "rows": [{"id": "row_y", "field": "posting", "op": "replace", "value": "Bridge"}],
            },
        )

        self._migrate()

        self.assertTrue((self.root / "mutation-sets" / f"{placed_id}.md").exists())
        placed_front, _ = _read(self._set_path(placed_id))
        self.assertNotIn("placed", placed_front)
        self.assertEqual(placed_front["title"], "Unrelated")

    def test_partial_run_crash_right_after_placed_set_match_completes_on_rerun(self) -> None:
        """Simulates a crash right after `_match_placed_sets` (review fix
        #2236): call the steps up to there directly, not the body rewrite —
        the scene body is still legacy-shaped and the placed file is already
        gone. A full re-run then finishes: the scene body converts, the
        chat's `staged_set` still names the converted set, and there is no
        staged duplicate left over."""
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        _write_scene(self.root / "scenes", "s1", body)
        placed_id = "mutation_set_placed1"
        _write_set(
            self.root / "mutation-sets",
            placed_id,
            {
                "title": "Promotion",
                "placed": True,
                "target_entry_type": "lore:character",
                "metadata": {"target_entity": "honor"},
                "rows": [{"id": "row_x", "field": "rank", "op": "replace", "value": "Captain"}],
            },
        )
        chat_folder = self.root / "chats"
        _write_text(
            chat_folder / "chat1.md",
            "---\n"
            + yaml.safe_dump(
                {
                    "id": "chat1",
                    "title": "Chat",
                    "entry_type": "chat:chat_session",
                    "metadata": {"staged_set": placed_id},
                },
                sort_keys=False,
            )
            + "---\n\n",
        )

        # The steps up to (and including) `_match_placed_sets` — where the
        # crash is simulated, before `_rewrite_scene_bodies` runs.
        ctx = ChainContext()
        _seed_entity_types(self.root, ctx)
        _mint_row_ids(self.root)
        paths_by_id = _scene_paths_by_id(self.root)
        converted = _convert_scenes(self.root, ctx, paths_by_id)
        _match_placed_sets(self.root, converted)

        scene_path = self.root / "scenes" / "s1.md"
        _, mid_body = _read(scene_path)
        self.assertIn("mutate:entity=", mid_body)  # "crash": body not yet rewritten
        self.assertFalse((self.root / "mutation-sets" / f"{placed_id}.md").exists())

        converted_id = derive_set_id("m1")
        self._migrate()  # a fresh process resuming would use a fresh ChainContext

        _, new_body = _read(scene_path)
        self.assertIn("mutate:set=", new_body)
        self.assertNotIn("mutate:entity=", new_body)
        self.assertFalse((self.root / "mutation-sets" / f"{placed_id}.md").exists())
        converted_front, _ = _read(self._set_path(converted_id))
        self.assertEqual(converted_front["title"], "Promotion")
        chat_front, _ = _read(chat_folder / "chat1.md")
        self.assertEqual(chat_front["metadata"]["staged_set"], converted_id)
        remaining = sorted(p.name for p in (self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(remaining, [f"{converted_id}.md"])  # no staged duplicate

    def test_partial_run_crash_mid_match_after_reference_rewrite_completes_on_rerun(self) -> None:
        """The reverse partial (review fix #2236): a crash inside
        `_match_placed_sets`, between `_rewrite_id_everywhere` and the
        placed file's `unlink` — the placed file's OWN `id:` has already been
        rewritten to the winner's id (it's one of `_layer_documents`'s
        targets too), but the file itself, its `placed: True` and the scene
        body are all still on disk exactly as before the rewrite. A full
        re-run still finishes cleanly."""
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        _write_scene(self.root / "scenes", "s1", body)
        converted_id = derive_set_id("m1")
        _write_set(
            self.root / "mutation-sets",
            converted_id,
            {
                "title": "Promotion",
                "target_entry_type": "lore:character",
                "metadata": {"target_entity": "honor"},
                "rows": [{"id": "m1", "field": "rank", "op": "replace", "value": "Captain"}],
            },
        )
        placed_path = _write_set(
            self.root / "mutation-sets",
            "mutation_set_placed1",
            {
                "id": converted_id,  # already rewritten by _rewrite_id_everywhere
                "title": "Promotion",
                "placed": True,
                "target_entry_type": "lore:character",
                "metadata": {"target_entity": "honor"},
                "rows": [{"id": "row_x", "field": "rank", "op": "replace", "value": "Captain"}],
            },
        )
        chat_folder = self.root / "chats"
        _write_text(
            chat_folder / "chat1.md",
            "---\n"
            + yaml.safe_dump(
                {
                    "id": "chat1",
                    "title": "Chat",
                    "entry_type": "chat:chat_session",
                    "metadata": {"staged_set": converted_id},  # already rewritten too
                },
                sort_keys=False,
            )
            + "---\n\n",
        )

        self._migrate()

        self.assertFalse(placed_path.exists())
        remaining = sorted(p.name for p in (self.root / "mutation-sets").glob("*.md"))
        self.assertEqual(remaining, [f"{converted_id}.md"])
        converted_front, _ = _read(self._set_path(converted_id))
        self.assertEqual(converted_front["title"], "Promotion")
        self.assertNotIn("placed", converted_front)
        _, new_body = _read(self.root / "scenes" / "s1.md")
        self.assertIn("mutate:set=", new_body)
        chat_front, _ = _read(chat_folder / "chat1.md")
        self.assertEqual(chat_front["metadata"]["staged_set"], converted_id)

    def test_placed_flag_dropped_from_every_set_regardless_of_scenes(self) -> None:
        set_id = "mutation_set_template1"
        _write_set(self.root / "mutation-sets", set_id, {"placed": True, "rows": []})

        self._migrate()

        front, _ = _read(self._set_path(set_id))
        self.assertNotIn("placed", front)


class _ChainEntityTypeTests(unittest.TestCase):
    """An entity defined in an ancestor layer, referenced by a marker in the
    descendant's own scene — needs `entity_types` threaded across the chain."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.book = self.series / "book"
        self.book_service = ProjectService.created_at(self.book, "Book")
        self.series_service = ProjectService.created_at(self.series, "Series")
        declare(self.book_service, self.book, [self.series], base=self.base)

        self.mira = self.series_service.create_lore_entry(
            CreateLoreEntryRequest(title="Mira", entry_type="lore:character")
        ).id
        scene = self.book_service.create_scene(CreateSceneRequest(title="Chapter"))
        self.scene_id = scene.id
        self.book_service.save_scene(
            scene.id,
            SaveSceneRequest(
                title="Chapter",
                body=f"<!-- mutate:entity={self.mira};field=mood;value=Grim;id=m1 -->",
            ),
        )
        self._rollback(self.series, 13)
        self._rollback(self.book, 13)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _rollback(root: Path, version: int) -> None:
        path = root / "project.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["schema_version"] = version
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def test_ancestor_lore_entry_resolves_for_target_entry_type(self) -> None:
        ProjectService.opened_at(self.book)

        self.assertEqual(read_project_version(self.book), 14)
        set_id = derive_set_id("m1")
        front, _ = _read(self.book / "mutation-sets" / f"{set_id}.md")
        self.assertEqual(front["target_entry_type"], "lore:character")
        self.assertEqual(front["metadata"]["target_entity"], self.mira)

    def test_ancestor_lore_entry_resolves_when_the_ancestor_is_already_at_v14(self) -> None:
        """The series is already at CURRENT_VERSION when the book opens — its
        own chain step never runs (`migration_runner._run_migrations` skips
        an up-to-date layer), so it never calls `_seed_entity_types` for its
        own lore. The book's own step must still see Mira's type by reading
        the series' lore folder directly (review fix #2236, ADR §12 step 0)."""
        self._rollback(self.series, CURRENT_VERSION)  # undo setUp's rollback

        ProjectService.opened_at(self.book)

        self.assertEqual(read_project_version(self.book), 14)
        self.assertEqual(read_project_version(self.series), CURRENT_VERSION)
        set_id = derive_set_id("m1")
        front, _ = _read(self.book / "mutation-sets" / f"{set_id}.md")
        self.assertEqual(front["target_entry_type"], "lore:character")
        self.assertEqual(front["metadata"]["target_entity"], self.mira)


class _ResolvedValueTests(unittest.TestCase):
    """After migration, what a scene resolves to must be exactly what the
    legacy fixture implied — the same expectations the old (pre-ADR-0095)
    resolution tests made, now read through the anchors+sets join (§5)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = ProjectService.created_at(self.root, "Book")
        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="text"),
                entry_type="lore:character",
            )
        )
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id
        scene1 = self.service.create_scene(CreateSceneRequest(title="One"))
        scene2 = self.service.create_scene(CreateSceneRequest(title="Two"))
        self.service.save_scene(
            scene1.id,
            SaveSceneRequest(
                title="One",
                body=f"<!-- mutate:entity={self.honor};field=rank;value=Captain;id=m1 -->",
            ),
        )
        self.service.save_scene(
            scene2.id,
            SaveSceneRequest(title="Two", body="No changes here."),
        )
        self.scene1_id, self.scene2_id = scene1.id, scene2.id

        path = self.root / "project.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["schema_version"] = 13
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_effective_state_after_migration_matches_the_legacy_fixture(self) -> None:
        service = ProjectService.opened_at(self.root)

        before = service.effective_state(self.honor, self.scene1_id)
        after = service.effective_state(self.honor, self.scene2_id)
        self.assertEqual(before.get("rank"), "Captain")
        self.assertEqual(after.get("rank"), "Captain")  # still live at the later scene


if __name__ == "__main__":
    unittest.main()
