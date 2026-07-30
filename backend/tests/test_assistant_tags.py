"""Assistant-tag governance — overview + merge/rename (#247 slice 2, PR-3).

Assistant tags are a flat, machine-global vocabulary (name + colour, no scope,
no layers — `assistant-tags.yaml`, #88). PR-3 gives them the rename/merge the
project side already has (`test_tags.py`), bounded to the reachable documents:
the machine store, machine + open-project assistant files (`metadata.tags`), and
the open project's prompt files (`metadata.assistant_tags`). What it deliberately
does NOT reach — an ancestor layer's (parent project's) files — is pinned by
`test_ancestor_assistant_reference_is_not_rewritten`, because "fixing" that would
mean a child project silently rewriting a parent's files.

The autouse conftest fixture redirects `config_path()` into a per-test tempdir,
so the machine store and `assistants_dir()` are isolated automatically.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import clear_test_scope, open_test_project

from app.main import app
from app.models import (
    AssistantTag,
    CreateAssistantEntryRequest,
    CreatePromptEntryRequest,
    MergeAssistantTagsRequest,
    SaveAssistantEntryRequest,
    SavePromptEntryRequest,
)
from app.services import machine_settings as ms
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class AssistantTagGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = ProjectService.created_at(self.root, "Book")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _make_machine_assistant(self, title: str, tags: list[str], *, layer_id: str = "") -> str:
        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title=title, entry_type="assistant:assistant", layer_id=layer_id)
        )
        self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(title=title, entry_type="assistant:assistant", metadata={"tags": tags}),
        )
        return entry.id

    def _make_prompt(self, title: str, assistant_tags: list[str]) -> str:
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title=title, entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title=title,
                body="body",
                entry_type="prompt:general",
                metadata={"assistant_tags": assistant_tags},
            ),
        )
        return entry.id

    def _store(self) -> dict[str, str | None]:
        return {tag.name: tag.color for tag in ms.load_assistant_tags()}

    def _assistant_tags(self, entry_id: str) -> list[str]:
        return list(self.service.read_assistant_entry(entry_id).metadata.get("tags") or [])

    def _prompt_tags(self, entry_id: str) -> list[str]:
        return list(self.service.read_prompt_entry(entry_id).metadata.get("assistant_tags") or [])

    # --- merge: the store ---------------------------------------------

    def test_merge_folds_store_and_survivor_keeps_its_own_colour(self) -> None:
        self._make_machine_assistant("Ed", ["Beta", "Editor"])
        ms.set_assistant_tag_color("Editor", "teal")
        ms.set_assistant_tag_color("Beta", "rose")

        result = self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        store = {tag.name: tag.color for tag in result.tags}
        self.assertEqual(store, {"Editor": "teal"})  # Beta gone; survivor keeps teal, not rose

    def test_merge_never_emits_a_duplicate_target_record(self) -> None:
        # The store can hold two casing variants of a name (register / set-colour
        # dedupe by EXACT name), and both match the merge target. The fold must
        # still write the survivor exactly once, keeping the first record's colour.
        ms.save_assistant_tags(
            [
                AssistantTag(name="Editor", color="teal"),
                AssistantTag(name="editor", color=None),
                AssistantTag(name="Beta", color=None),
            ]
        )

        result = self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        editor_records = [tag for tag in result.tags if tag.name.lower() == "editor"]
        self.assertEqual([(tag.name, tag.color) for tag in editor_records], [("Editor", "teal")])

    def test_merge_into_a_brand_new_target_leaves_it_colourless(self) -> None:
        self._make_machine_assistant("Ed", ["Beta"])
        ms.set_assistant_tag_color("Beta", "rose")

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Reviewer"))

        self.assertEqual(self._store(), {"Reviewer": None})

    # --- merge: the documents -----------------------------------------

    def test_merge_rewrites_and_dedupes_assistant_tags_field(self) -> None:
        aid = self._make_machine_assistant("Ed", ["Beta", "Editor"])

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        # Both source and target were present → deduped to one.
        self.assertEqual(self._assistant_tags(aid), ["Editor"])

    def test_merge_rewrites_prompt_assistant_tags_field(self) -> None:
        self._make_machine_assistant("Ed", ["Editor"])
        pid = self._make_prompt("Draft", ["Beta"])

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        self.assertEqual(self._prompt_tags(pid), ["Editor"])

    def test_rename_is_a_single_source_merge_that_migrates_uses(self) -> None:
        aid = self._make_machine_assistant("Ed", ["Beta"])
        pid = self._make_prompt("Draft", ["Beta"])

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Reviewer"))

        self.assertEqual(self._store(), {"Reviewer": None})
        self.assertEqual(self._assistant_tags(aid), ["Reviewer"])
        self.assertEqual(self._prompt_tags(pid), ["Reviewer"])

    def test_merge_recases_the_survivor_and_its_uses_to_the_target_casing(self) -> None:
        # Store + document hold a lowercase 'editor'; merging into 'Editor' both
        # recases the store record and folds the document values to one 'Editor'.
        aid = self._make_machine_assistant("Ed", ["Beta", "editor"])

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        self.assertEqual(list(self._store()), ["Editor"])
        self.assertEqual(self._assistant_tags(aid), ["Editor"])

    def test_merge_of_several_sources_folds_all_into_the_target(self) -> None:
        aid = self._make_machine_assistant("Ed", ["Beta", "Proofer", "Editor"])

        self.service.merge_assistant_tags(
            MergeAssistantTagsRequest(sources=["Beta", "Proofer"], target="Editor")
        )

        self.assertEqual(self._assistant_tags(aid), ["Editor"])
        self.assertEqual(set(self._store()), {"Editor"})

    # --- overview ------------------------------------------------------

    def test_overview_counts_across_assistants_prompts_and_store(self) -> None:
        self._make_machine_assistant("Ed", ["Beta", "Editor"])
        self._make_prompt("Draft", ["Beta"])
        ms.set_assistant_tag_color("Beta", "rose")
        ms.register_assistant_tags(["Unused"])  # registered but on no document

        overview = {usage.name: usage for usage in self.service.read_assistant_tags_overview().tags}

        self.assertEqual(overview["Beta"].count, 2)  # one assistant + one prompt
        self.assertEqual(overview["Beta"].color, "rose")
        self.assertEqual(overview["Editor"].count, 1)
        self.assertEqual(overview["Unused"].count, 0)  # zero-use registered tag still shows

    def test_overview_without_a_project_open_reads_the_machine_roster(self) -> None:
        # A machine assistant exists; then resolve unbound (no project).
        self._make_machine_assistant("Ed", ["Beta"])
        unbound = ProjectService(None)

        overview = {usage.name: usage.count for usage in unbound.read_assistant_tags_overview().tags}

        self.assertEqual(overview.get("Beta"), 1)  # machine assistant still counted

    # --- validation ----------------------------------------------------

    def test_merge_rejects_empty_sources(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["  "], target="Editor"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_merge_rejects_blank_target(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="   "))
        self.assertEqual(ctx.exception.status_code, 422)


class AssistantTagReachabilityTests(unittest.TestCase):
    """The reach bound (ADR-0045): a merge rewrites machine + open-project files,
    never an ancestor layer's (a parent project's)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.root = self.universe / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(
            layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder
        )

    def _make_assistant(self, title: str, tags: list[str], *, layer_id: str | None) -> str:
        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title=title, entry_type="assistant:assistant", layer_id=layer_id or "")
            if layer_id is not None
            else CreateAssistantEntryRequest(title=title, entry_type="assistant:assistant")
        )
        self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(title=title, entry_type="assistant:assistant", metadata={"tags": tags}),
        )
        return entry.id

    def test_ancestor_assistant_reference_is_not_rewritten(self) -> None:
        # An assistant owned by the parent (universe) project, tagged Beta.
        ancestor_id = self._make_assistant("Sage", ["Beta"], layer_id=self._layer_id(self.universe))
        # An assistant owned by the OPEN project (book01), also tagged Beta.
        owned_id = self._make_assistant("Ed", ["Beta"], layer_id=self._layer_id(self.root))

        self.service.merge_assistant_tags(MergeAssistantTagsRequest(sources=["Beta"], target="Editor"))

        # The open project's own file is rewritten; the parent project's file is
        # left alone — its stale Beta survives and would re-register on that
        # project's next save (the accepted reach bound, ADR-0045).
        self.assertEqual(self.service.read_assistant_entry(owned_id).metadata.get("tags"), ["Editor"])
        self.assertEqual(self.service.read_assistant_entry(ancestor_id).metadata.get("tags"), ["Beta"])


class AssistantTagEndpointTests(unittest.TestCase):
    """The two new routes through the ASGI surface — the header-resolved project
    scope reaches the mixin, and errors translate to HTTP codes."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "book"
        self.service = open_test_project(self.root, "Book")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        clear_test_scope()
        self.temp_dir.cleanup()

    def _make_assistant(self, title: str, tags: list[str]) -> None:
        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title=title, entry_type="assistant:assistant", layer_id="")
        )
        self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(title=title, entry_type="assistant:assistant", metadata={"tags": tags}),
        )

    def test_overview_then_merge_over_http(self) -> None:
        self._make_assistant("Ed", ["Beta", "Editor"])

        overview = self.client.get("/api/assistant-tags/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        counts = {tag["name"]: tag["count"] for tag in overview.json()["tags"]}
        self.assertEqual(counts, {"Beta": 1, "Editor": 1})

        merged = self.client.post("/api/assistant-tags/merge", json={"sources": ["Beta"], "target": "Editor"})
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertEqual([tag["name"] for tag in merged.json()["tags"]], ["Editor"])

    def test_merge_over_http_422s_on_blank_target(self) -> None:
        response = self.client.post("/api/assistant-tags/merge", json={"sources": ["Beta"], "target": "   "})
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
