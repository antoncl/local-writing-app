from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.services import migrations
from app.services.migrations import (
    BACKUP_DIRNAME,
    CURRENT_VERSION,
    migrate_project,
    read_project_version,
)
from app.services.project_service import ProjectService


class MigrationFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_stamps_current_schema_version(self) -> None:
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)

    def test_create_initializes_research_artifacts(self) -> None:
        # A fresh project ships research/notes/ + an empty
        # research.structure.yaml so the research feature has somewhere
        # to land without a migration step.
        self.assertTrue((self.root / "research" / "notes").is_dir())
        structure_path = self.root / "research.structure.yaml"
        self.assertTrue(structure_path.exists())
        tree = yaml.safe_load(structure_path.read_text(encoding="utf-8"))
        self.assertEqual(tree["root"]["title"], "Research")
        self.assertEqual(tree["root"]["children"], [])

    def test_fresh_project_open_runs_no_migrations(self) -> None:
        reopened_service = ProjectService()
        reopened_service.open_project(self.root)
        self.assertEqual(reopened_service.last_migrations, [])
        self.assertFalse((self.root / BACKUP_DIRNAME).exists())

    def test_pre_framework_project_runs_all_pending_migrations(self) -> None:
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data.pop("schema_version", None)
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.assertEqual(read_project_version(self.root), 0)

        applied = migrate_project(self.root)
        # Every migration registered with a target <= CURRENT_VERSION runs.
        self.assertEqual(len(applied), len(migrations.MIGRATIONS))
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)

    def test_pending_migration_runs_and_creates_backup(self) -> None:
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 0
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        sentinel_path = self.root / "_migration_sentinel.txt"

        def fake_migration(root: Path) -> None:
            (root / "_migration_sentinel.txt").write_text("ran", encoding="utf-8")

        original_registry = list(migrations.MIGRATIONS)
        original_current = migrations.CURRENT_VERSION
        try:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.append((99, "test sentinel migration", fake_migration))
            migrations.CURRENT_VERSION = 99

            applied = migrate_project(self.root)
            self.assertEqual(len(applied), 1)
            self.assertIn("v99", applied[0])
            self.assertTrue(sentinel_path.exists())
            self.assertEqual(read_project_version(self.root), 99)

            backup_dir = self.root / BACKUP_DIRNAME
            self.assertTrue(backup_dir.exists())
            archives = list(backup_dir.glob("v*-*.zip"))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as archive:
                names = set(archive.namelist())
            self.assertIn("project.yaml", {n.replace("\\", "/") for n in names})
            self.assertFalse(any(n.startswith(BACKUP_DIRNAME) for n in names))
        finally:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.extend(original_registry)
            migrations.CURRENT_VERSION = original_current

    def test_fresh_project_does_not_create_snippets_folder(self) -> None:
        """Snippets are now a prompt sub-type. New projects no longer create snippets/.
        Existing v1 projects still get snippets/ via the v1→v2 migration for backwards
        compatibility; see test_v1_project_migrates_to_v2_creating_snippets_folder."""
        self.assertFalse((self.root / "snippets").exists())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertEqual(self.service.last_migrations, [])

    def test_v1_project_migrates_creating_snippets(self) -> None:
        """An existing v1 project gains snippets/ on next open.

        It does NOT gain project.md: the v2→v3 back-fill was removed with #343
        (it wrote a constant id). A folder that old is expected not to exist.
        """
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 1
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        # Simulate a v1 project on disk: snippets/ and project.md don't exist
        snippets = self.root / "snippets"
        if snippets.exists():
            for child in snippets.iterdir():
                child.unlink()
            snippets.rmdir()
        project_md = self.root / "project.md"
        if project_md.exists():
            project_md.unlink()
        self.assertFalse(snippets.exists())
        self.assertFalse(project_md.exists())

        reopened = ProjectService()
        reopened.open_project(self.root)
        self.assertTrue(snippets.is_dir())
        self.assertFalse(project_md.exists())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        # Every registered migration ran (v2, v4, v5 — 3 is retired).
        self.assertEqual(len(reopened.last_migrations), len(migrations.MIGRATIONS))
        joined = " ".join(reopened.last_migrations)
        self.assertIn("snippets", joined)
        self.assertIn("research", joined)
        self.assertIn("ai_invocations", joined)

        # Backup was created
        backup_dir = self.root / BACKUP_DIRNAME
        self.assertTrue(backup_dir.exists())
        archives = list(backup_dir.glob("v1-*.zip"))
        self.assertEqual(len(archives), 1)

    def test_validate_surfaces_migrations_applied(self) -> None:
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data.pop("schema_version", None)
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        def fake_migration(root: Path) -> None:
            return None

        original_registry = list(migrations.MIGRATIONS)
        original_current = migrations.CURRENT_VERSION
        try:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.append((42, "noop", fake_migration))
            migrations.CURRENT_VERSION = 42

            reopened_service = ProjectService()
            reopened_service.open_project(self.root)
            self.assertEqual(len(reopened_service.last_migrations), 1)

            report = reopened_service.validate_project()
            self.assertEqual(len(report.migrations_applied), 1)
            self.assertIn("v42", report.migrations_applied[0])
        finally:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.extend(original_registry)
            migrations.CURRENT_VERSION = original_current


class ChatCostMigrationTests(unittest.TestCase):
    """v3→v4: existing chat cost_usd_total moves into ai_invocations.yaml."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_v3_chat_with_total(self, chat_id: str, total: float) -> None:
        chats_dir = self.root / "chats"
        chats_dir.mkdir(exist_ok=True)
        chat_path = chats_dir / f"{chat_id}.yaml"
        chat_path.write_text(
            yaml.safe_dump(
                {
                    "id": chat_id,
                    "title": "Legacy chat",
                    "created_at": "2026-06-01T12:00:00+00:00",
                    "updated_at": "2026-06-02T15:30:00+00:00",
                    "messages": [],
                    "cost_usd_total": total,
                    "target_scene_id": "scene_legacy",
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_migration_moves_chat_total_into_log_and_zeros_yaml(self) -> None:
        self._seed_v3_chat_with_total("chat_legacy_one", 0.42)
        self._seed_v3_chat_with_total("chat_legacy_two", 0.13)
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 3
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        reopened = ProjectService()
        reopened.open_project(self.root)

        log_data = yaml.safe_load((self.root / "ai_invocations.yaml").read_text(encoding="utf-8"))
        rows = log_data["invocations"]
        by_chat = {r["chat_session_id"]: r for r in rows}
        self.assertIn("chat_legacy_one", by_chat)
        self.assertIn("chat_legacy_two", by_chat)
        self.assertAlmostEqual(by_chat["chat_legacy_one"]["cost_usd"], 0.42, places=6)
        self.assertAlmostEqual(by_chat["chat_legacy_two"]["cost_usd"], 0.13, places=6)
        self.assertEqual(by_chat["chat_legacy_one"]["scene_id"], "scene_legacy")
        # YAML cost_usd_total zeroed in place.
        chat_yaml = yaml.safe_load(
            (self.root / "chats" / "chat_legacy_one.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(chat_yaml["cost_usd_total"], 0.0)

    def test_migration_skips_chats_with_zero_total(self) -> None:
        self._seed_v3_chat_with_total("chat_zero", 0.0)
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 3
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        reopened = ProjectService()
        reopened.open_project(self.root)
        log_path = self.root / "ai_invocations.yaml"
        if log_path.exists():
            log_data = yaml.safe_load(log_path.read_text(encoding="utf-8")) or {}
            self.assertEqual(log_data.get("invocations", []), [])


class ResearchStructureMigrationTests(unittest.TestCase):
    """v4→v5: research/notes/ folder + empty research.structure.yaml."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_migration_creates_research_folder_and_structure_file(self) -> None:
        # Roll the project back to v4 and remove research artifacts so
        # the migration has something to do.
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 4
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        research_dir = self.root / "research"
        structure_path = self.root / "research.structure.yaml"
        if structure_path.exists():
            structure_path.unlink()
        if research_dir.exists():
            for child in (research_dir / "notes").iterdir():
                child.unlink()
            (research_dir / "notes").rmdir()
            research_dir.rmdir()
        self.assertFalse(research_dir.exists())
        self.assertFalse(structure_path.exists())

        reopened = ProjectService()
        reopened.open_project(self.root)

        self.assertTrue((self.root / "research" / "notes").is_dir())
        self.assertTrue(structure_path.exists())
        tree = yaml.safe_load(structure_path.read_text(encoding="utf-8"))
        self.assertEqual(tree["root"]["type"], "root")
        self.assertEqual(tree["root"]["title"], "Research")
        self.assertEqual(tree["root"]["children"], [])
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)

    def test_migration_preserves_existing_research_structure_file(self) -> None:
        # A user-edited research tree must not be clobbered by the
        # back-fill. Simulate a project that already has the file.
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 4
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        structure_path = self.root / "research.structure.yaml"
        structure_path.write_text(
            yaml.safe_dump(
                {
                    "root": {
                        "id": "root",
                        "type": "root",
                        "title": "Research",
                        "children": [
                            {
                                "id": "topic_1",
                                "type": "topic",
                                "title": "Industrial Revolution",
                                "children": [],
                            }
                        ],
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        reopened = ProjectService()
        reopened.open_project(self.root)

        tree = yaml.safe_load(structure_path.read_text(encoding="utf-8"))
        self.assertEqual(len(tree["root"]["children"]), 1)
        self.assertEqual(tree["root"]["children"][0]["title"], "Industrial Revolution")


if __name__ == "__main__":
    unittest.main()
