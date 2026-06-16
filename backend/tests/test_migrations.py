from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.services import migrations
from app.services.migrations import (
    CURRENT_VERSION,
    BACKUP_DIRNAME,
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

    def test_fresh_project_has_snippets_folder(self) -> None:
        """v2 ships snippets/ via create_project; no migration needed for fresh projects."""
        self.assertTrue((self.root / "snippets").is_dir())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertEqual(self.service.last_migrations, [])

    def test_v1_project_migrates_to_v2_creating_snippets_folder(self) -> None:
        """An existing v1 project gains snippets/ on next open."""
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 1
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        # Simulate a v1 project on disk: snippets/ doesn't exist
        snippets = self.root / "snippets"
        if snippets.exists():
            for child in snippets.iterdir():
                child.unlink()
            snippets.rmdir()
        self.assertFalse(snippets.exists())

        reopened = ProjectService()
        reopened.open_project(self.root)
        self.assertTrue(snippets.is_dir())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        self.assertEqual(len(reopened.last_migrations), 1)
        self.assertIn("v2", reopened.last_migrations[0])
        self.assertIn("snippets", reopened.last_migrations[0])

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


if __name__ == "__main__":
    unittest.main()
