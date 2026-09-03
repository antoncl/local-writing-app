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

    def test_create_scaffolds_tags_folder(self) -> None:
        # Z10(c), round-2 review #1807: `create_project` writes `tags/`
        # where it used to write `tags.yaml` (ADR-0082 slice 4 M5).
        self.assertTrue((self.root / "tags").is_dir())

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
        # Every registered step is one of the three ADR-0071/ADR-0082 shapes —
        # no bare tuples/functions.
        for step in migrations.MIGRATIONS:
            self.assertIsInstance(step, (RootMigration, DocumentMigration, migrations.ChainMigration))

        def noop(doc: MigratableDocument) -> MigratableDocument:
            return MigratableDocument(dict(doc.front_matter), doc.body)

        def must_not_run(root, ctx) -> None:
            raise AssertionError("migrate_document must never dispatch to a ChainMigration")

        original_registry, original_current = self._register_document_step(99, noop)
        try:
            # A RootMigration AND a ChainMigration (Z10f, round-2 review
            # #1807) in the registry are both ignored by migrate_document;
            # only the DocumentMigration we just registered is dispatched
            # to. A ChainMigration's `fn` takes `(root, ctx)` — if
            # migrate_document ever mis-dispatched to it with a single-arg
            # call, this would raise a TypeError; if it dispatched at all,
            # `must_not_run` raises.
            migrations.MIGRATIONS.insert(
                0, RootMigration(50, "root step ignored by migrate_document", lambda root: None)
            )
            migrations.MIGRATIONS.insert(
                0, migrations.ChainMigration(49, "chain step ignored by migrate_document", must_not_run)
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


class TagMigrationHelperTests(unittest.TestCase):
    """Round-2 review of #1785 (PR #1807): unit tests for the pure per-value
    helpers `_migrate_layer_tags` composes, isolated from a whole project
    tree — a fresh `tmp_path`-scoped `tags/` folder stands in for a layer's
    own vocabulary folder."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.layer_root = Path(self.temp_dir.name).resolve() / "layer"
        (self.layer_root / "tags").mkdir(parents=True)
        self.machine_root = Path(self.temp_dir.name).resolve() / "machine"
        (self.machine_root / "tags").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_z2_nested_item_group_member_tags_are_converted(self) -> None:
        # Z2: `characters: [{name, tags: [Villain]}]` — a list-of-dicts
        # item-group member (ADR-0081), not a top-level metadata key.
        ctx = migrations.ChainContext()
        front_matter = {
            "metadata": {
                "characters": [
                    {"name": "Bob", "tags": ["Villain"]},
                    {"name": "Ann"},
                ]
            }
        }
        changed = migrations._convert_document_metadata(
            front_matter, kind="lore", layer_root=self.layer_root, machine_root=self.machine_root, ctx=ctx
        )
        self.assertTrue(changed)
        characters = front_matter["metadata"]["characters"]
        self.assertEqual(len(characters[0]["tags"]), 1)
        tag_id = characters[0]["tags"][0]
        self.assertRegex(tag_id, r"^tag_[0-9a-f]{10}$")
        self.assertEqual(ctx.name_to_id.get("villain"), tag_id)
        self.assertNotIn("tags", characters[1])

    def test_z3_assistant_legacy_and_existing_tags_are_unioned(self) -> None:
        # Z3: an assistant document carrying BOTH the pre-rename `tags` key
        # AND an already-present `assistant_tags` — union, order-preserving,
        # deduped, never an overwrite.
        ctx = migrations.ChainContext()
        existing_id = migrations.mint_tag_node(self.machine_root / "tags", "Editor", "tag:assistant_tag")
        ctx.machine_names["editor"] = existing_id
        front_matter = {
            "metadata": {
                "tags": ["Editor", "Proofreader"],  # Editor already known; Proofreader is new
                "assistant_tags": [existing_id],  # already carries Editor's id
            }
        }
        changed = migrations._convert_document_metadata(
            front_matter, kind="assistant", layer_root=self.layer_root, machine_root=self.machine_root, ctx=ctx
        )
        self.assertTrue(changed)
        self.assertNotIn("tags", front_matter["metadata"])
        result = front_matter["metadata"]["assistant_tags"]
        # Existing id first (order-preserving), Editor not duplicated, Proofreader appended.
        self.assertEqual(result[0], existing_id)
        self.assertEqual(len(result), 2)  # deduped: Editor collapses onto the existing id
        proofreader_id = ctx.machine_names["proofreader"]
        self.assertIn(proofreader_id, result)

    def test_z4_a_legacy_name_shaped_like_an_id_is_still_minted(self) -> None:
        # Z4: "already an id" is identity (present in a known map), never a
        # regex match on shape — a legacy tag literally NAMED like an id
        # must still convert.
        ctx = migrations.ChainContext()
        resolved, changed = migrations._resolve_name_list(
            ["tag_0123456789"], self.layer_root / "tags", ctx.name_to_id, "tag:tag", (ctx.name_to_id, ctx.machine_names)
        )
        self.assertTrue(changed)
        self.assertEqual(len(resolved), 1)
        minted_id = resolved[0]
        self.assertNotEqual(minted_id, "tag_0123456789")
        self.assertRegex(minted_id, r"^tag_[0-9a-f]{10}$")
        # The literal string is now a title on disk, not treated as an id.
        titles = migrations._tag_node_names(self.layer_root / "tags")
        self.assertIn("tag_0123456789", titles)

    def test_z4_a_real_known_id_passes_through_unchanged(self) -> None:
        # The flip side: a value that IS a known id (present in ctx) is left
        # alone, not re-resolved/re-minted.
        ctx = migrations.ChainContext()
        real_id = migrations.mint_tag_node(self.layer_root / "tags", "Coastal", "tag:tag")
        ctx.name_to_id["coastal"] = real_id
        resolved, changed = migrations._resolve_name_list(
            [real_id], self.layer_root / "tags", ctx.name_to_id, "tag:tag", (ctx.name_to_id, ctx.machine_names)
        )
        self.assertFalse(changed)
        self.assertEqual(resolved, [real_id])

    def test_z7_an_unresolved_tagged_leaf_becomes_the_empty_expr(self) -> None:
        # Z7 / ADR-0082 §6: an unresolvable `tagged:` name is DROPPED — the
        # leaf becomes `{}` (selects nothing, ADR-0036), not left stale.
        ctx = migrations.ChainContext()
        unresolved: list[str] = []
        node, changed = migrations._convert_view_expr_node({"tagged": "Nowhere"}, ctx, unresolved)
        self.assertTrue(changed)
        self.assertEqual(node, {})
        self.assertEqual(unresolved, ["tagged:Nowhere"])

    def test_z7_an_unresolved_tagged_leaf_nested_in_intersect_becomes_empty(self) -> None:
        ctx = migrations.ChainContext()
        known_id = migrations.mint_tag_node(self.layer_root / "tags", "Mirrors", "tag:tag")
        ctx.name_to_id["mirrors"] = known_id
        unresolved: list[str] = []
        spec = {"intersect": [{"tagged": "Mirrors"}, {"tagged": "Nowhere"}]}
        node, changed = migrations._convert_view_expr_node(spec, ctx, unresolved)
        self.assertTrue(changed)
        self.assertEqual(node, {"intersect": [{"tagged": known_id}, {}]})
        self.assertEqual(unresolved, ["tagged:Nowhere"])

    def test_z7_an_unresolved_chat_ref_is_dropped_from_the_picks_list(self) -> None:
        # Z7 / ADR-0082 §6: an unresolvable chat tag-ref is REMOVED from the
        # picks list, not left as a stale reference.
        ctx = migrations.ChainContext()
        known_id = migrations.mint_tag_node(self.layer_root / "tags", "Mirrors", "tag:tag")
        ctx.name_to_id["mirrors"] = known_id
        unresolved: list[str] = []
        picks = [
            {"id": "tag:lore:Mirrors", "kind": "tag", "title": "Mirrors"},
            {"id": "tag:lore:Nowhere", "kind": "tag", "title": "Nowhere"},
            {"id": "lore_a", "kind": "lore", "title": "Ally"},  # concrete pick, untouched
        ]
        new_list, changed = migrations._convert_chat_ref_list(picks, ctx, unresolved)
        self.assertTrue(changed)
        self.assertEqual(len(new_list), 2)
        self.assertEqual(new_list[0]["id"], f"tagged:lore:{known_id}")
        self.assertEqual(new_list[1]["id"], "lore_a")
        self.assertEqual(unresolved, ["tag:lore:Nowhere"])

    def test_z9_the_tag_family_folder_is_never_walked_as_a_node_document(self) -> None:
        # Step 1 already minted these; the generic document walk must skip
        # `tags/` entirely rather than re-open what it just wrote. A lore
        # file is ALSO seeded so the walk genuinely runs (proving the skip
        # is deliberate, not just an empty folder).
        calls: list[str] = []
        original = migrations._migrate_one_node_document

        def spy(path, *, kind, **kwargs):
            calls.append(kind)
            return original(path, kind=kind, **kwargs)

        (self.layer_root / "tags.yaml").write_text("tags:" + chr(10) + "  - Coastal", encoding="utf-8")
        lore_folder = self.layer_root / "lore"
        lore_folder.mkdir()
        (lore_folder / "ally.md").write_text(
            chr(10).join(["---", "id: ally", "title: Ally", "entry_type: lore:character", "---", ""]),
            encoding="utf-8",
        )
        migrations._migrate_one_node_document = spy
        try:
            ctx = migrations.ChainContext()
            migrations._migrate_layer_tags(self.layer_root, ctx)
        finally:
            migrations._migrate_one_node_document = original
        self.assertIn("lore", calls)
        self.assertNotIn("tag", calls)


if __name__ == "__main__":
    unittest.main()
