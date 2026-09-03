"""ADR-0082 slice 4 (#1785): the tags-to-node-model migration.

A two-layer chain (`series` -> `book`), with `universe` — a bare folder, never
declared, never a project — sitting between the machine root and `series`, so
opening `book` proves the ancestor walk skips a non-project folder rather than
tripping over it. `series` and `book` both carry pre-migration `tags.yaml`
registries and pre-migration `tags`/`assistant_tags` occurrences across every
shape M4 converts; the machine config dir carries its own pre-migration
`assistant-tags.yaml` roster (M3). Opening `book` runs the whole chain: the
machine once-step, then `series`'s own ladder, then `book`'s.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from layer_fixtures import declare

from app.models import LoreEntry
from app.scope import WorkScope
from app.services import machine_settings as ms_service
from app.services.migrations import CURRENT_VERSION, read_project_version
from app.services.project.overrides import OVERRIDE_ENTRY_TYPE, OVERRIDES_FOLDER
from app.services.project_service import ProjectService


def _tag_titles(folder: Path) -> dict[str, str]:
    """`{title: id}` over every `*.md` directly in `folder` (a `tags/` dir) —
    the test's own reader, deliberately independent of `migrations.py`'s."""
    out: dict[str, str] = {}
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = yaml.safe_load(text.split("---\n", 2)[1])
        out[front["title"]] = front["id"]
    return out


class TagsChainMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        # `universe` is a plain folder — never scaffolded, never declared —
        # between the machine root and `series` (the "skipped, no project.yaml"
        # ancestor).
        self.universe = self.base / "universe"
        self.series = self.universe / "series"
        self.book = self.series / "book"
        self.book_service = ProjectService.created_at(self.book, "Book")
        self.series_service = ProjectService.created_at(self.series, "Series")

        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        # AFTER the patch — declare() writes the machine root through config_path().
        declare(self.book_service, self.book, [self.series], base=self.base)

        self._seed_series_tags_yaml()
        self._seed_book_tags_yaml()
        self.coastal_lore_id = self._seed_series_lore_entry()
        self.scene_id = self._seed_book_scene()
        self._seed_book_override()
        self._seed_book_view()
        self._seed_book_chat()
        self._seed_book_prompt()
        self._seed_book_schema_field()
        self._seed_machine_assistant_tags()

        # `created_at` stamps a fresh project straight to CURRENT_VERSION (it
        # never runs migrations on first open, migrations.py's own docstring) —
        # roll both layers back one version so the v10 chain step is PENDING,
        # simulating a project the tags.yaml fixtures above predate.
        self._rollback_schema_version(self.series, CURRENT_VERSION - 1)
        self._rollback_schema_version(self.book, CURRENT_VERSION - 1)

        ProjectService.opened_at(self.book)
        self.series_tags = _tag_titles(self.series / "tags")
        self.book_tags = _tag_titles(self.book / "tags")
        self.coastal_id = self.series_tags["Coastal"]
        self.mirrors_id = self.book_tags["Mirrors"]
        self.untracked_id = self.book_tags["Untracked"]
        self.machine_tags = _tag_titles(ms_service.tags_dir())
        self.editor_id = self.machine_tags["Editor"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- fixture helpers ---------------------------------------------------

    @staticmethod
    def _rollback_schema_version(root: Path, version: int) -> None:
        manifest_path = root / "project.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = version
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _seed_series_tags_yaml(self) -> None:
        (self.series / "tags.yaml").write_text(
            yaml.safe_dump({"tags": [{"name": "Coastal", "color": "sea-green"}, "Doubling"]}, sort_keys=False),
            encoding="utf-8",
        )

    def _seed_book_tags_yaml(self) -> None:
        (self.book / "tags.yaml").write_text(
            yaml.safe_dump({"tags": ["coastal", "Mirrors"]}, sort_keys=False), encoding="utf-8"
        )

    def _seed_series_lore_entry(self) -> str:
        path = self.series / "lore" / "coastal_watch.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.series_service._write_lore_entry_file(
            path,
            LoreEntry(
                id="coastal_watch",
                title="Coastal Watch",
                body="",
                revision="",
                entry_type="lore:character",
                metadata={"tags": ["Coastal"]},
            ),
        )
        return "coastal_watch"

    def _seed_book_scene(self) -> str:
        from app.models import CreateSceneRequest

        scene = self.book_service.create_scene(CreateSceneRequest(title="Opening"))
        path = self.book_service._path_for_node_id(scene.id, "manuscript")
        front_matter, body = self.book_service._read_markdown_with_front_matter(path, strict=True)
        metadata = dict(front_matter.get("metadata") or {})
        metadata["tags"] = ["coastal", "Mirrors", "Untracked"]
        front_matter = dict(front_matter)
        front_matter["metadata"] = metadata
        self.book_service._write_markdown_with_front_matter(path, front_matter, body)
        return scene.id

    def _seed_book_override(self) -> None:
        folder = self.book / OVERRIDES_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        self.book_service._write_node_entry_file(
            folder / "coastal_watch_override.md",
            "override_test1",
            "",
            OVERRIDE_ENTRY_TYPE,
            {},
            "",
            extra={
                "target": self.coastal_lore_id,
                "rows": [{"field": "tags", "op": "replace", "value": "coastal,Mirrors"}],
            },
        )

    def _seed_book_view(self) -> None:
        folder = self.book / "views"
        folder.mkdir(parents=True, exist_ok=True)
        self.book_service._write_node_entry_file(
            folder / "coastal_view.md",
            "view_test1",
            "Coastal View",
            "view:view",
            {},
            "",
            extra={"spec": {"kind": "lore", "expr": {"tagged": "Mirrors"}}},
        )

    def _seed_book_chat(self) -> str:
        folder = self.book / "chats"
        folder.mkdir(parents=True, exist_ok=True)
        picks = [{"id": "tag:lore:Mirrors", "kind": "tag", "title": "Mirrors"}]
        self.book_service._write_node_entry_file(
            folder / "chat_test1.md",
            "chat_test1",
            "Research chat",
            "chat:chat_session",
            {},
            "",
            extra={"inputs": {"context": json.dumps(picks)}},
            omit_empty_metadata=True,
        )
        return "chat_test1"

    def _seed_book_prompt(self) -> None:
        folder = self.book / "prompts"
        folder.mkdir(parents=True, exist_ok=True)
        self.book_service._write_node_entry_file(
            folder / "revise_prompt.md",
            "prompt_test1",
            "Revise plotline",
            "prompt:base",
            {"assistant_tags": ["Editor"]},
            "",
        )

    def _seed_book_schema_field(self) -> None:
        schema_path = self.book / "metadata.schema.yaml"
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        data.setdefault("fields", {})["custom_tags"] = {"name": "Custom Tags", "type": "tags"}
        schema_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _seed_machine_assistant_tags(self) -> None:
        # `declare()` already wrote config.yaml (default_projects_folder); add
        # `version: 1` explicitly (the pre-M3 state — 1 is also the model
        # default, but spelled out here to match the spec fixture).
        config_path = self.config_dir / "config.yaml"
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        data["version"] = 1
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        (self.config_dir / "assistant-tags.yaml").write_text(
            yaml.safe_dump({"tags": [{"name": "Editor"}]}, sort_keys=False), encoding="utf-8"
        )
        assistants_folder = ms_service.assistants_dir()
        assistants_folder.mkdir(parents=True, exist_ok=True)
        self.book_service._write_node_entry_file(
            assistants_folder / "roster_assistant.md",
            "assistant_roster1",
            "Roster Assistant",
            "assistant:assistant",
            {"tags": ["Editor"]},
            "",
        )

    # --- assertions ----------------------------------------------------------

    def test_both_layers_stamped_and_backed_up_ancestor_folder_untouched(self) -> None:
        self.assertEqual(read_project_version(self.series), CURRENT_VERSION)
        self.assertEqual(read_project_version(self.book), CURRENT_VERSION)
        self.assertTrue(list((self.series / ".migration-backups").glob("v*-*.zip")))
        self.assertTrue(list((self.book / ".migration-backups").glob("v*-*.zip")))
        # `universe` sits between the machine root and `series` but is never a
        # project (no `project.yaml`) — the ancestor walk skips it entirely.
        self.assertFalse((self.universe / ".migration-backups").exists())

    def test_one_coastal_tag_minted_at_the_series_not_re_minted_at_the_book(self) -> None:
        self.assertIn("Coastal", self.series_tags)
        self.assertIn("Doubling", self.series_tags)
        # Book's lower-cased `coastal` resolves to the series node rather than
        # minting a second one — only Mirrors/Untracked are book-local.
        self.assertEqual(set(self.book_tags), {"Mirrors", "Untracked"})

    def test_tags_yaml_renamed_at_both_layers(self) -> None:
        self.assertFalse((self.series / "tags.yaml").exists())
        self.assertTrue((self.series / "tags.yaml.migrated").exists())
        self.assertFalse((self.book / "tags.yaml").exists())
        self.assertTrue((self.book / "tags.yaml.migrated").exists())

    def test_series_lore_entry_carries_the_coastal_id(self) -> None:
        lore_front = yaml.safe_load(
            (self.series / "lore" / "coastal_watch.md").read_text(encoding="utf-8").split("---\n", 2)[1]
        )
        self.assertEqual(lore_front["metadata"]["tags"], [self.coastal_id])

    def test_scene_reads_through_the_api_with_resolved_titles(self) -> None:
        reopened = ProjectService(WorkScope(root=self.book))
        scene = reopened.read_scene(self.scene_id)
        self.assertEqual(scene.metadata["tags"], [self.coastal_id, self.mirrors_id, self.untracked_id])
        resolved = reopened.resolve_references([self.mirrors_id, self.untracked_id])
        by_id = {c.id: c for c in resolved.candidates}
        self.assertTrue(by_id[self.mirrors_id].found)
        self.assertEqual(by_id[self.mirrors_id].title, "Mirrors")
        self.assertTrue(by_id[self.untracked_id].found)
        self.assertEqual(by_id[self.untracked_id].title, "Untracked")

    def test_override_row_carries_ids(self) -> None:
        override_front = yaml.safe_load(
            (self.book / OVERRIDES_FOLDER / "coastal_watch_override.md")
            .read_text(encoding="utf-8")
            .split("---\n", 2)[1]
        )
        self.assertEqual(override_front["rows"][0]["value"], f"{self.coastal_id},{self.mirrors_id}")

    def test_saved_view_tagged_leaf_carries_the_id(self) -> None:
        view_front = yaml.safe_load(
            (self.book / "views" / "coastal_view.md").read_text(encoding="utf-8").split("---\n", 2)[1]
        )
        self.assertEqual(view_front["spec"]["expr"]["tagged"], self.mirrors_id)

    def test_chat_ref_carries_the_id_title_unchanged(self) -> None:
        chat_front = yaml.safe_load(
            (self.book / "chats" / "chat_test1.md").read_text(encoding="utf-8").split("---\n", 2)[1]
        )
        picks = json.loads(chat_front["inputs"]["context"])
        self.assertEqual(picks[0]["id"], f"tagged:lore:{self.mirrors_id}")
        self.assertEqual(picks[0]["title"], "Mirrors")

    def test_schema_field_converts_to_entity_ref_list_with_create_missing(self) -> None:
        schema_data = yaml.safe_load((self.book / "metadata.schema.yaml").read_text(encoding="utf-8"))
        custom_field = schema_data["fields"]["custom_tags"]
        self.assertEqual(custom_field["type"], "entity_ref_list")
        self.assertEqual(
            custom_field["picker_config"],
            {"sources": [{"kind": "tag", "expr": {"type": "tag:tag"}}], "create_missing": True},
        )

    def test_machine_assistant_tag_minted_roster_rewritten_version_bumped(self) -> None:
        # Machine: exactly one `tag:assistant_tag` node, minted from
        # `assistant-tags.yaml`.
        self.assertEqual(set(self.machine_tags), {"Editor"})

        prompt_front = yaml.safe_load(
            (self.book / "prompts" / "revise_prompt.md").read_text(encoding="utf-8").split("---\n", 2)[1]
        )
        self.assertEqual(prompt_front["metadata"]["assistant_tags"], [self.editor_id])

        assistant_front = yaml.safe_load(
            (ms_service.assistants_dir() / "roster_assistant.md").read_text(encoding="utf-8").split("---\n", 2)[1]
        )
        self.assertEqual(assistant_front["metadata"]["assistant_tags"], [self.editor_id])
        self.assertNotIn("tags", assistant_front["metadata"])

        self.assertFalse((self.config_dir / "assistant-tags.yaml").exists())
        self.assertTrue((self.config_dir / "assistant-tags.yaml.migrated").exists())
        self.assertEqual(ms_service.load_settings().version, 2)

    def test_rerun_is_a_no_op(self) -> None:
        reopened_again = ProjectService.opened_at(self.book)
        self.assertEqual(reopened_again.last_migrations, ())
        self.assertEqual(set(_tag_titles(self.book / "tags")), {"Mirrors", "Untracked"})
        self.assertEqual(set(_tag_titles(self.series / "tags")), {"Coastal", "Doubling"})

    def test_opening_series_afterwards_runs_no_migration(self) -> None:
        series_reopened = ProjectService.opened_at(self.series)
        self.assertEqual(series_reopened.last_migrations, ())


if __name__ == "__main__":
    unittest.main()
