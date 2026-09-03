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
    DocumentMigration,
    MigratableDocument,
    RootMigration,
    _lift_plot_template_genre,
    migrate_document,
    migrate_project,
    read_project_version,
)
from app.services.project_service import ProjectService


class MigrationFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "project"
        self.service = ProjectService.created_at(self.root, "Test Project")

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

    def test_backfill_narration_cascade_fields_adds_to_existing_schema(self) -> None:
        # v5→v6 (ADR-0079): an existing project's metadata.schema.yaml predates the
        # cascade_fields key; the migration seeds it while preserving other content.
        schema_path = self.root / "metadata.schema.yaml"
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        data.pop("cascade_fields", None)  # simulate a pre-v6 file
        data.setdefault("fields", {})["custom"] = {"name": "Custom", "type": "text"}
        schema_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        migrations._backfill_narration_cascade_fields(self.root)

        after = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(after["cascade_fields"], ["pov_mode", "pov"])
        self.assertIn("custom", after["fields"])  # existing content preserved

    def test_backfill_narration_cascade_fields_is_idempotent(self) -> None:
        # Scaffold already seeds cascade_fields (incl. tense, #1737); re-running the
        # v6 step must not duplicate and must leave the scaffold's extras intact.
        schema_path = self.root / "metadata.schema.yaml"
        migrations._backfill_narration_cascade_fields(self.root)
        migrations._backfill_narration_cascade_fields(self.root)
        after = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(after["cascade_fields"], ["pov_mode", "pov", "tense"])

    def test_backfill_tense_cascade_field_adds_to_a_v6_schema(self) -> None:
        # v6→v7 (#1737): a project that ran v6 has [pov_mode, pov] but not tense;
        # the v7 step appends tense while preserving order and other content.
        schema_path = self.root / "metadata.schema.yaml"
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        data["cascade_fields"] = ["pov_mode", "pov"]  # simulate a post-v6, pre-v7 file
        schema_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        migrations._backfill_tense_cascade_field(self.root)

        after = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(after["cascade_fields"], ["pov_mode", "pov", "tense"])
        # Idempotent — re-running is a no-op.
        migrations._backfill_tense_cascade_field(self.root)
        self.assertEqual(
            yaml.safe_load(schema_path.read_text(encoding="utf-8"))["cascade_fields"],
            ["pov_mode", "pov", "tense"],
        )

    def test_backfill_narration_cascade_fields_creates_missing_schema(self) -> None:
        # A legacy project with no metadata.schema.yaml still gets the cascade.
        schema_path = self.root / "metadata.schema.yaml"
        schema_path.unlink()
        migrations._backfill_narration_cascade_fields(self.root)
        self.assertTrue(schema_path.exists())
        after = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(after["cascade_fields"], ["pov_mode", "pov"])

    def test_migrate_project_backfills_cascade_fields_end_to_end(self) -> None:
        # Proves the v6 step is REGISTERED and WIRED, not just that the function
        # works in isolation: a mis-registered step passes the count test but
        # never writes cascade_fields.
        schema_path = self.root / "metadata.schema.yaml"
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        data.pop("cascade_fields", None)
        schema_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        manifest_path = self.root / "project.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 5  # just below v6
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        migrate_project(self.root)

        after = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertIn("pov_mode", after.get("cascade_fields", []))
        self.assertIn("pov", after.get("cascade_fields", []))
        self.assertIn("tense", after.get("cascade_fields", []))  # v7 (#1737)
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)

    def test_fresh_project_open_runs_no_migrations(self) -> None:
        reopened_service = ProjectService.opened_at(self.root)
        self.assertEqual(reopened_service.last_migrations, ())
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
            migrations.MIGRATIONS.append(RootMigration(99, "test sentinel migration", fake_migration))
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
        self.assertEqual(self.service.last_migrations, ())

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

        ProjectService.opened_at(self.root)
        self.assertTrue(snippets.is_dir())
        self.assertFalse(project_md.exists())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        # Assert the EFFECTS of every registered migration, not their
        # descriptions: a step that silently no-ops still reports its own
        # description, and comparing the count to len(MIGRATIONS) is
        # self-referential — both survive a no-op mutant.
        self.assertTrue((self.root / "research" / "notes").is_dir())
        self.assertTrue((self.root / "research.structure.yaml").exists())

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
            migrations.MIGRATIONS.append(RootMigration(42, "noop", fake_migration))
            migrations.CURRENT_VERSION = 42

            reopened_service = ProjectService.opened_at(self.root)
            self.assertEqual(len(reopened_service.last_migrations), 1)

            report = reopened_service.validate_project()
            self.assertEqual(len(report.migrations_applied), 1)
            self.assertIn("v42", report.migrations_applied[0])
        finally:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.extend(original_registry)
            migrations.CURRENT_VERSION = original_current


class DocumentMigrationFrameworkTests(unittest.TestCase):
    """migrate_document (ADR-0071 §1/§4): the isolated, no-root entry point.
    None of these tests touch a project root or tmp_path — a DocumentMigration
    only ever sees a MigratableDocument."""

    def _register_document_step(self, version: int, fn) -> tuple[list, int]:
        """Monkeypatch a single DocumentMigration into MIGRATIONS with
        CURRENT_VERSION raised to its version; returns the state to restore."""
        original_registry = list(migrations.MIGRATIONS)
        original_current = migrations.CURRENT_VERSION
        migrations.MIGRATIONS.clear()
        migrations.MIGRATIONS.append(DocumentMigration(version, "rename status to state", fn))
        migrations.CURRENT_VERSION = version
        return original_registry, original_current

    def _restore(self, original_registry: list, original_current: int) -> None:
        migrations.MIGRATIONS.clear()
        migrations.MIGRATIONS.extend(original_registry)
        migrations.CURRENT_VERSION = original_current

    def test_migrate_document_applies_a_document_step_with_no_root(self) -> None:
        def rename_status_to_state(doc: MigratableDocument) -> MigratableDocument:
            front_matter = dict(doc.front_matter)
            front_matter["state"] = front_matter.pop("status")
            return MigratableDocument(front_matter, doc.body + "\nmigrated")

        original_registry, original_current = self._register_document_step(99, rename_status_to_state)
        try:
            doc = MigratableDocument({"id": "x", "status": "draft"}, "body text")
            result = migrate_document(doc, from_version=98)
            self.assertEqual(result.front_matter, {"id": "x", "state": "draft"})
            self.assertEqual(result.body, "body text\nmigrated")
        finally:
            self._restore(original_registry, original_current)

    def test_migrate_document_skips_steps_at_or_below_from_version(self) -> None:
        def rename_status_to_state(doc: MigratableDocument) -> MigratableDocument:
            front_matter = dict(doc.front_matter)
            front_matter["state"] = front_matter.pop("status")
            return MigratableDocument(front_matter, doc.body + "\nmigrated")

        original_registry, original_current = self._register_document_step(99, rename_status_to_state)
        try:
            doc = MigratableDocument({"id": "x", "status": "draft"}, "body text")
            result = migrate_document(doc, from_version=99)
            self.assertEqual(result.front_matter, {"id": "x", "status": "draft"})
            self.assertEqual(result.body, "body text")
        finally:
            self._restore(original_registry, original_current)

    def test_registry_steps_are_typed_root_or_document(self) -> None:
        # Every registered step is one of the two ADR-0071 shapes — no bare
        # tuples/functions.
        for step in migrations.MIGRATIONS:
            self.assertIsInstance(step, (RootMigration, DocumentMigration))

        def noop(doc: MigratableDocument) -> MigratableDocument:
            return MigratableDocument(dict(doc.front_matter), doc.body)

        original_registry, original_current = self._register_document_step(99, noop)
        try:
            # A RootMigration in the registry is ignored by migrate_document; only
            # the DocumentMigration we just registered is dispatched to.
            migrations.MIGRATIONS.insert(
                0, RootMigration(50, "root step ignored by migrate_document", lambda root: None)
            )
            doc = MigratableDocument({"id": "x"}, "body")
            result = migrate_document(doc, from_version=0)
            self.assertEqual(result.front_matter, {"id": "x"})
            self.assertEqual(result.body, "body")
        finally:
            self._restore(original_registry, original_current)


class PlotTemplateGenreMigrationTests(unittest.TestCase):
    """v7→v8 (#1744): lift `plot:template` genre out of the `template:` spec block
    into a node-metadata field. Pure per-document transform — no root, no service."""

    @staticmethod
    def _doc(front_matter: dict) -> MigratableDocument:
        return MigratableDocument(front_matter, "# guide")

    def test_lifts_template_genre_into_metadata(self) -> None:
        out = _lift_plot_template_genre(
            self._doc(
                {
                    "id": "plot_x",
                    "entry_type": "plot:template",
                    "template": {"slug": "x", "genre": "Noir — rain and regret."},
                    "metadata": {"beats": []},
                }
            )
        )
        self.assertNotIn("genre", out.front_matter["template"])
        self.assertEqual(out.front_matter["metadata"]["genre"], "Noir — rain and regret.")
        self.assertEqual(out.front_matter["metadata"]["beats"], [])  # existing metadata kept

    def test_seeds_a_metadata_block_when_the_template_has_none(self) -> None:
        out = _lift_plot_template_genre(
            self._doc(
                {
                    "id": "plot_x",
                    "entry_type": "plot:template",
                    "template": {"genre": "Heist — a crew, a mark, a plan gone sideways."},
                }
            )
        )
        self.assertEqual(out.front_matter["metadata"]["genre"], "Heist — a crew, a mark, a plan gone sideways.")

    def test_is_idempotent_once_genre_has_moved(self) -> None:
        # No genre left in the block → the same object comes back, so the document
        # pass's changed-check writes nothing (no mtime churn on re-open).
        doc = self._doc(
            {
                "id": "plot_x",
                "entry_type": "plot:template",
                "template": {"slug": "x"},
                "metadata": {"genre": "Noir — rain and regret."},
            }
        )
        self.assertIs(_lift_plot_template_genre(doc), doc)

    def test_never_clobbers_an_existing_metadata_genre(self) -> None:
        out = _lift_plot_template_genre(
            self._doc(
                {
                    "id": "plot_x",
                    "entry_type": "plot:template",
                    "template": {"genre": "from the block"},
                    "metadata": {"genre": "already here"},
                }
            )
        )
        self.assertEqual(out.front_matter["metadata"]["genre"], "already here")
        self.assertNotIn("genre", out.front_matter["template"])

    def test_is_a_no_op_for_a_non_template_document(self) -> None:
        # A plotline already carries genre in its own metadata; the lift must not
        # touch any document that is not a plot:template.
        doc = self._doc(
            {
                "id": "plotline_x",
                "entry_type": "plot:plotline",
                "template": {"genre": "ignored — not a template node"},
                "metadata": {"genre": "Romance"},
            }
        )
        self.assertIs(_lift_plot_template_genre(doc), doc)


class ResearchStructureMigrationTests(unittest.TestCase):
    """v4→v5: research/notes/ folder + empty research.structure.yaml."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "project"
        self.service = ProjectService.created_at(self.root, "Test Project")

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

        ProjectService.opened_at(self.root)

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

        ProjectService.opened_at(self.root)

        tree = yaml.safe_load(structure_path.read_text(encoding="utf-8"))
        self.assertEqual(len(tree["root"]["children"]), 1)
        self.assertEqual(tree["root"]["children"][0]["title"], "Industrial Revolution")


class InvocationLedgerCsvMigrationTests(unittest.TestCase):
    """v8→v9 (#1801): the ai_invocations ledger moves from a YAML list to an
    append-only CSV. The transform runs off the root and reuses the ledger's
    shared column contract, so a migrated row reads back through the live
    reader identically."""

    _ROWS = [
        {
            "id": "inv_1",
            "ts": "2026-08-30T10:00:00+00:00",
            "chat_session_id": "chat_1",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "usage": {
                "input_tokens": 4200,
                "cached_input_tokens": 1300,
                "cache_write_tokens": 800,
                "output_tokens": 1100,
            },
            "cost_usd": 0.049,
        },
        {
            "id": "inv_2",
            "ts": "2026-08-31T09:00:00+00:00",
            "scene_id": "manuscript_1",
            "provider": "ollama",
            "model": "llama3",
            "cost_usd": None,  # unpriced row
        },
    ]

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "project"
        self.service = ProjectService.created_at(self.root, "Ledger Project")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_yaml(self, payload: object) -> None:
        (self.root / "ai_invocations.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

    def test_converts_yaml_list_and_reads_back_through_the_live_reader(self) -> None:
        self._write_yaml({"invocations": self._ROWS})
        migrations._migrate_invocations_to_csv(self.root)

        self.assertFalse((self.root / "ai_invocations.yaml").exists())
        self.assertTrue((self.root / "ai_invocations.csv").exists())

        rows = self.service._read_ai_invocations_raw()
        self.assertEqual([row["id"] for row in rows], ["inv_1", "inv_2"])
        self.assertEqual(rows[0]["usage"]["input_tokens"], 4200)
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.049, places=6)
        # Unpriced row: cost stays None (not 0.0), no usage captured.
        self.assertIsNone(rows[1]["cost_usd"])
        self.assertNotIn("usage", rows[1])

    def test_converts_the_historical_bare_list_shape(self) -> None:
        # The oldest on-disk shape was a bare top-level list, not
        # {invocations: [...]}; both must convert.
        self._write_yaml(self._ROWS)
        migrations._migrate_invocations_to_csv(self.root)
        rows = self.service._read_ai_invocations_raw()
        self.assertEqual([row["id"] for row in rows], ["inv_1", "inv_2"])

    def test_idempotent_when_csv_already_present_drops_a_stray_yaml(self) -> None:
        # A leftover YAML beside an existing CSV: the CSV is authoritative and
        # is left byte-for-byte untouched; the stale YAML is removed.
        csv_path = self.root / "ai_invocations.csv"
        csv_path.write_text("id,ts\ninv_keep,t\n", encoding="utf-8")
        self._write_yaml({"invocations": self._ROWS})

        migrations._migrate_invocations_to_csv(self.root)

        self.assertFalse((self.root / "ai_invocations.yaml").exists())
        self.assertEqual(csv_path.read_text(encoding="utf-8"), "id,ts\ninv_keep,t\n")

    def test_no_op_when_no_ledger_exists(self) -> None:
        migrations._migrate_invocations_to_csv(self.root)
        self.assertFalse((self.root / "ai_invocations.csv").exists())

    def test_migration_is_registered_and_runs_on_open(self) -> None:
        # Proves v9 is WIRED (not just that the function works): roll the
        # project back to v8, drop a YAML ledger, reopen — the ledger becomes
        # CSV, its rows survive, and the version stamps forward.
        manifest_path = self.root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = 8
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self._write_yaml({"invocations": self._ROWS})

        reopened = ProjectService.opened_at(self.root)

        self.assertFalse((self.root / "ai_invocations.yaml").exists())
        self.assertTrue((self.root / "ai_invocations.csv").exists())
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        summary = reopened.ai_cost_summary()
        self.assertEqual(summary.count, 2)
        self.assertAlmostEqual(summary.total_cost_usd, 0.049, places=6)


if __name__ == "__main__":
    unittest.main()
