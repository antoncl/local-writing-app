"""The project-wide document pass wired into the open path (#366 slice 2,
ADR-0071 §2-§5).

`test_migrations.py` covers the pure framework (`migrate_document`, the typed
registry) and the pre-existing root-migration/reopen tests, which now exercise
`_run_migrations` under the hood via the `migrate_project` shim. This file
covers what only the ProjectService-backed pass can prove: the document walk
reaches index nodes *and* the open layer's own `overrides/*.md`, an
ancestor-owned document is left alone, no-churn when nothing is pending, and
the end-of-ladder stamp + backup for a mixed root+document migration.
"""

from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    LoreEntry,
    SaveLoreEntryRequest,
)
from app.scope import WorkScope
from app.services import migrations
from app.services.migrations import (
    BACKUP_DIRNAME,
    DocumentMigration,
    MigratableDocument,
    RootMigration,
    migrate_document,
    read_project_version,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.overrides import OVERRIDE_ENTRY_TYPE, OVERRIDES_FOLDER
from app.services.project_service import ProjectService


def _rename_priority_to_urgency(doc: MigratableDocument) -> MigratableDocument:
    """Fixture DocumentMigration spanning >=2 encodings (ADR-0071 §3): an
    override row's `field` key AND an entry's `metadata:` key. Kind-aware —
    it reads `entry_type` to pick the representation, exactly what a real
    content step must do."""
    front_matter = dict(doc.front_matter)
    if front_matter.get("entry_type") == OVERRIDE_ENTRY_TYPE:
        rows = front_matter.get("rows")
        if isinstance(rows, list):
            new_rows = [dict(row) for row in rows]
            changed = False
            for row in new_rows:
                if row.get("field") == "priority":
                    row["field"] = "urgency"
                    changed = True
            if changed:
                front_matter["rows"] = new_rows
    else:
        metadata = front_matter.get("metadata")
        if isinstance(metadata, dict) and "priority" in metadata:
            metadata = dict(metadata)
            metadata["urgency"] = metadata.pop("priority")
            front_matter["metadata"] = metadata
    return MigratableDocument(front_matter, doc.body)


class ProjectDocumentPassTests(unittest.TestCase):
    """A 2-layer chain (`base` -> `root`/book) so an ancestor-owned entry and a
    book-owned override on it are both reachable from one fixture."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "book"
        self.service = ProjectService.created_at(self.root, "Book")
        declare_full_chain(self.service, self.root, self.base)
        # `priority` is chain-wide on lore:character, so a real override save
        # (the ADR-0039 rail picker path) can target it.
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {"priority": {"name": "priority", "type": "text", "label": "Priority"}},
                "entry_types": {"lore:character": {"fields": ["priority"]}},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- fixture helpers -------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_lore_at(self, folder: Path, node_id: str, title: str, metadata: dict, entry_type: str) -> Path:
        """Write a node file directly at a layer, bypassing the create dance
        (the same pattern `test_layer_overrides.py` uses)."""
        writer = ProjectService(WorkScope(root=folder))
        path = folder / "lore" / f"{node_id}.md"
        writer._write_lore_entry_file(
            path,
            LoreEntry(id=node_id, title=title, body="", revision="", entry_type=entry_type, metadata=metadata),
        )
        return path

    def _inject_metadata(self, path: Path, extra: dict) -> None:
        """Hand-set an extra metadata key the create path never seeds — the
        stand-in for a pre-migration document already on disk."""
        front_matter, body = self.service._read_markdown_with_front_matter(path, strict=True)
        metadata = dict(front_matter.get("metadata") or {})
        metadata.update(extra)
        front_matter = dict(front_matter)
        front_matter["metadata"] = metadata
        self.service._write_markdown_with_front_matter(path, front_matter, body)

    def _seed_owned_documents(self) -> tuple[Path, Path, Path, Path]:
        """Seed: an ancestor-owned lore entry ("ally"), a book-owned lore entry,
        a book-owned scene, and a book-owned override on "ally". Returns the
        four paths (ally, hero, scene, override)."""
        ally_path = self._write_lore_at(self.base, "ally", "Ally", {"priority": "high"}, "lore:character")

        hero = self.service.create_lore_entry(CreateLoreEntryRequest(title="Hero"))
        hero_path = self.service._path_for_node_id(hero.id, "lore")
        self._inject_metadata(hero_path, {"priority": "medium"})

        scene = self.service.create_scene(CreateSceneRequest(title="Opening"))
        scene_path = self.service._path_for_node_id(scene.id, "manuscript")
        self._inject_metadata(scene_path, {"priority": "low"})

        self.service.save_lore_entry(
            "ally",
            SaveLoreEntryRequest(
                title="Ally",
                body="",
                entry_type="lore:character",
                metadata={"priority": "urgent"},
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        override_path = next((self.root / OVERRIDES_FOLDER).glob("*.md"))
        return ally_path, hero_path, scene_path, override_path

    def _register_steps(self, steps: list, version: int) -> tuple[list, int]:
        original_registry = list(migrations.MIGRATIONS)
        original_current = migrations.CURRENT_VERSION
        migrations.MIGRATIONS.clear()
        migrations.MIGRATIONS.extend(steps)
        migrations.CURRENT_VERSION = version
        return original_registry, original_current

    def _restore(self, original_registry: list, original_current: int) -> None:
        migrations.MIGRATIONS.clear()
        migrations.MIGRATIONS.extend(original_registry)
        migrations.CURRENT_VERSION = original_current

    # --- acceptance #2: project == per-document equivalence --------------

    def test_project_migration_equals_per_document_migration(self) -> None:
        ally_path, hero_path, scene_path, override_path = self._seed_owned_documents()
        pre = {
            path: self.service._read_markdown_with_front_matter(path, strict=True)
            for path in (hero_path, scene_path, override_path)
        }

        original_registry, original_current = self._register_steps(
            [DocumentMigration(99, "rename priority to urgency", _rename_priority_to_urgency)], 99
        )
        try:
            from_version = read_project_version(self.root)
            ProjectService.opened_at(self.root)

            for path, (front_matter, body) in pre.items():
                expected = migrate_document(MigratableDocument(front_matter, body), from_version)
                actual = self.service._read_markdown_with_front_matter(path, strict=True)
                self.assertEqual(actual, (expected.front_matter, expected.body), path)

            hero_front, _ = self.service._read_markdown_with_front_matter(hero_path, strict=True)
            self.assertEqual(hero_front["metadata"]["urgency"], "medium")
            self.assertNotIn("priority", hero_front["metadata"])

            scene_front, _ = self.service._read_markdown_with_front_matter(scene_path, strict=True)
            self.assertEqual(scene_front["metadata"]["urgency"], "low")

            override_front, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
            self.assertEqual(override_front["rows"], [{"field": "urgency", "op": "replace", "value": "urgent"}])
        finally:
            self._restore(original_registry, original_current)
        # ally_path unused beyond seeding here — covered by the owned-only test.
        self.assertTrue(ally_path.exists())

    # --- owned-only --------------------------------------------------------

    def test_ancestor_owned_document_is_not_rewritten(self) -> None:
        ally_path, _hero_path, _scene_path, _override_path = self._seed_owned_documents()
        before = ally_path.read_text(encoding="utf-8")

        original_registry, original_current = self._register_steps(
            [DocumentMigration(99, "rename priority to urgency", _rename_priority_to_urgency)], 99
        )
        try:
            ProjectService.opened_at(self.root)
            # "ally" is owned by `base`, not the open project `root` — untouched.
            self.assertEqual(ally_path.read_text(encoding="utf-8"), before)
        finally:
            self._restore(original_registry, original_current)

    # --- override coverage --------------------------------------------------

    def test_override_row_is_transformed(self) -> None:
        _ally_path, _hero_path, _scene_path, override_path = self._seed_owned_documents()

        original_registry, original_current = self._register_steps(
            [DocumentMigration(99, "rename priority to urgency", _rename_priority_to_urgency)], 99
        )
        try:
            ProjectService.opened_at(self.root)
            front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
            self.assertEqual(front_matter["rows"], [{"field": "urgency", "op": "replace", "value": "urgent"}])
        finally:
            self._restore(original_registry, original_current)

    # --- no-churn ------------------------------------------------------------

    def test_no_pending_document_step_rewrites_nothing(self) -> None:
        _ally_path, hero_path, scene_path, override_path = self._seed_owned_documents()
        paths = [hero_path, scene_path, override_path]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

        # No fixture step registered — the real registry has no pending steps
        # for a project just stamped to CURRENT_VERSION.
        ProjectService.opened_at(self.root)

        for path in paths:
            after = (path.read_bytes(), path.stat().st_mtime_ns)
            self.assertEqual(after, before[path], path)

    # --- stamp + backup for a mixed migration ---------------------------------

    def test_mixed_migration_stamps_once_and_backs_up(self) -> None:
        _ally_path, hero_path, _scene_path, _override_path = self._seed_owned_documents()
        sentinel_path = self.root / "_root_step_sentinel.txt"

        def fake_root_step(root: Path) -> None:
            (root / "_root_step_sentinel.txt").write_text("ran", encoding="utf-8")

        original_registry, original_current = self._register_steps(
            [
                RootMigration(90, "root sentinel", fake_root_step),
                DocumentMigration(91, "rename priority to urgency", _rename_priority_to_urgency),
            ],
            91,
        )
        stamp_calls: list[int] = []
        original_write = migrations.write_project_version

        def counting_write(root: Path, version: int) -> None:
            stamp_calls.append(version)
            original_write(root, version)

        migrations.write_project_version = counting_write
        try:
            service = ProjectService.opened_at(self.root)
            self.assertTrue(sentinel_path.exists())
            self.assertEqual(read_project_version(self.root), 91)
            # Stamped exactly once, at the end of the whole ladder — not once
            # per step (ADR-0071 §4).
            self.assertEqual(stamp_calls, [91])
            self.assertEqual(len(service.last_migrations), 2)

            backup_dir = self.root / BACKUP_DIRNAME
            self.assertTrue(backup_dir.exists())
            self.assertTrue(list(backup_dir.glob("v*-*.zip")))

            hero_front, _ = self.service._read_markdown_with_front_matter(hero_path, strict=True)
            self.assertEqual(hero_front["metadata"]["urgency"], "medium")
        finally:
            migrations.write_project_version = original_write
            self._restore(original_registry, original_current)

    # --- failure recovery (review finding, #366 slice 2) ---------------------

    def test_failed_document_migration_leaves_project_rerunnable(self) -> None:
        """A step that raises on one document must leave the stamp unmoved,
        the pre-migration content recoverable from the backup, and a retry
        (with the step fixed) must converge — including over any document
        that was already rewritten before the failure (idempotency)."""
        _ally_path, hero_path, scene_path, override_path = self._seed_owned_documents()
        scene_front, _ = self.service._read_markdown_with_front_matter(scene_path, strict=True)
        scene_id = scene_front["id"]

        state = {"raise": True}

        def _rename_but_raise_on_scene(doc: MigratableDocument) -> MigratableDocument:
            if state["raise"] and doc.front_matter.get("id") == scene_id:
                raise RuntimeError("simulated failure on the scene document")
            return _rename_priority_to_urgency(doc)

        original_registry, original_current = self._register_steps(
            [DocumentMigration(99, "rename priority to urgency (raises on scene)", _rename_but_raise_on_scene)],
            99,
        )
        try:
            from_version = read_project_version(self.root)
            with self.assertRaises(ProjectServiceError):
                ProjectService.opened_at(self.root)
            # The stamp is written once, at the end of the whole ladder — a
            # step raising mid-pass must leave it unmoved, not at 99.
            self.assertEqual(read_project_version(self.root), from_version)

            backup_dir = self.root / BACKUP_DIRNAME
            backups = list(backup_dir.glob(f"v{from_version}-*.zip"))
            self.assertTrue(backups)
            with zipfile.ZipFile(backups[0]) as archive:
                entry_name = next(name for name in archive.namelist() if name.endswith(hero_path.name))
                backed_up_content = archive.read(entry_name).decode("utf-8")
            self.assertIn("priority", backed_up_content)

            # Flip the fixture to the non-raising rename-everything version and
            # retry: the project must converge to 99, migrating both documents
            # — including any left mid-ladder by the failed run.
            state["raise"] = False
            ProjectService.opened_at(self.root)
            self.assertEqual(read_project_version(self.root), 99)

            hero_front, _ = self.service._read_markdown_with_front_matter(hero_path, strict=True)
            self.assertIn("urgency", hero_front["metadata"])
            self.assertNotIn("priority", hero_front["metadata"])

            scene_front, _ = self.service._read_markdown_with_front_matter(scene_path, strict=True)
            self.assertIn("urgency", scene_front["metadata"])
            self.assertNotIn("priority", scene_front["metadata"])
        finally:
            self._restore(original_registry, original_current)
        self.assertTrue(override_path.exists())

    def test_completed_migration_is_noop_on_reopen(self) -> None:
        """Once a document pass has converged and stamped CURRENT_VERSION,
        re-opening the same project must not touch any file again —
        `pending_migrations` is empty, so the doc pass does not run."""
        _ally_path, hero_path, scene_path, override_path = self._seed_owned_documents()
        paths = [hero_path, scene_path, override_path]

        original_registry, original_current = self._register_steps(
            [DocumentMigration(99, "rename priority to urgency", _rename_priority_to_urgency)], 99
        )
        try:
            ProjectService.opened_at(self.root)
            self.assertEqual(read_project_version(self.root), 99)
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

            ProjectService.opened_at(self.root)

            for path in paths:
                after = (path.read_bytes(), path.stat().st_mtime_ns)
                self.assertEqual(after, before[path], path)
            self.assertEqual(read_project_version(self.root), 99)
        finally:
            self._restore(original_registry, original_current)


if __name__ == "__main__":
    unittest.main()
