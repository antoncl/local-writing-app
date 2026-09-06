"""The search corpus (ADR-0085 §1, slice 1): `search` reads a memory-only
cache built from the resolved node index's winners view instead of scanning
files, and that cache rides the node index's own lifecycle — dropped by
`NodeIndexGate.invalidate()`, patched by `_apply_index_write`.

These tests pin: parity with today's scene/lore search shape, occurrence-level
body hits (one per match, not one per line), the corpus reaching every
prose-bodied kind the index lists (research, prompt, plot) while excluding
chats outright, inherited-lore layering (`owned`), the corpus staying correct
across save/delete/rename/schema-write without a project reopen, the
cold-build read count, and the `rglob` guard on `search.py`.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import (
    ChatSessionMessage,
    CreateCardRequest,
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    MetadataFieldDefinition,
    SaveCardRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveResearchNoteRequest,
    SaveSceneRequest,
    SearchRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.node_index_gate import node_index_gate
from app.services.project.search_corpus import CorpusEntry, SearchCorpus, search_corpus
from app.services.project_service import ProjectService

PROJECT_SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "project"


class SearchCorpusTestCase(unittest.TestCase):
    """Base fixture: a fresh single-layer project. The gate/corpus are
    process-global, so every test starts and ends by dropping them — a stale
    hold from a previous test would otherwise leak into a `peek(root)` for a
    coincidentally-equal (never actually, since roots are per-tempdir) root."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Test Project")
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    # ---- helpers ----------------------------------------------------------

    def _new_scene(self, title: str, body: str) -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title=title, body=body, base_revision=scene.revision),
        )
        return scene.id

    def _new_lore(self, title: str, body: str) -> str:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title=title))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(title=title, body=body, base_revision=entry.revision),
        )
        return entry.id

    def _search(self, query: str):
        return self.service.search(SearchRequest(query=query)).hits


class ParityTests(SearchCorpusTestCase):
    def test_scene_and_lore_hits_match_todays_shape(self) -> None:
        scene_id = self._new_scene("Aetheria Notes", "The Aetheria gate")
        lore_id = self._new_lore("Notes", "Aetheria fell")

        hits = self._search("aetheria")

        manuscript_hits = [h for h in hits if h.kind == "manuscript"]
        lore_hits = [h for h in hits if h.kind == "lore"]
        self.assertEqual(len(manuscript_hits), 2, manuscript_hits)
        meta_hit = next(h for h in manuscript_hits if h.field == "metadata")
        body_hit = next(h for h in manuscript_hits if h.field == "body")

        self.assertEqual(meta_hit.line, 1)
        self.assertTrue(meta_hit.path.endswith(" metadata"), meta_hit.path)
        self.assertTrue(meta_hit.owned)

        self.assertEqual(body_hit.excerpt, "The Aetheria gate")
        self.assertEqual(body_hit.line, 1)
        self.assertEqual(body_hit.start, body_hit.excerpt.index("Aetheria"))
        self.assertEqual(body_hit.end, body_hit.start + len("Aetheria"))
        self.assertTrue(body_hit.owned)
        scene_path = self.service._path_for_node_id(scene_id, "manuscript")
        self.assertEqual(body_hit.revision, self.service._revision(scene_path))

        self.assertEqual(len(lore_hits), 1, lore_hits)
        self.assertEqual(lore_hits[0].field, "body")
        self.assertTrue(lore_hits[0].owned)
        lore_path = self.service._path_for_node_id(lore_id, "lore")
        index = self.service._build_node_index(self.root)
        expected_lore_revision = self.service._composite_revision(
            [lore_path, *self.service._override_paths_for_target(index, lore_id)]
        )
        self.assertEqual(lore_hits[0].revision, expected_lore_revision)


class OccurrenceLevelTests(SearchCorpusTestCase):
    def test_two_occurrences_on_one_line_yield_two_hits(self) -> None:
        self._new_scene("Scene", "Aetheria and Aetheria")

        hits = [h for h in self._search("aetheria") if h.field == "body"]

        self.assertEqual(len(hits), 2, hits)
        self.assertEqual(hits[0].line, hits[1].line)
        self.assertNotEqual(hits[0].start, hits[1].start)


class NewKindsTests(SearchCorpusTestCase):
    def test_research_prompt_and_plot_bodies_are_searchable(self) -> None:
        tree = self.service.create_research_node(
            CreateStructureNodeRequest(title="Research topic", entry_type="research:note")
        )
        note = next(child for child in tree.root.children if child.type == "research:note")
        self.service.save_research_note(
            note.scene_id,
            SaveResearchNoteRequest(title="Research topic", body="Aetheria research notes"),
        )

        prompt = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Prompt A", entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            prompt.id,
            SavePromptEntryRequest(
                title="Prompt A",
                body="Aetheria prompt body",
                base_revision=prompt.revision,
                entry_type="prompt:general",
            ),
        )

        card = self.service.create_card(CreateCardRequest(title="Card A"))
        self.service.save_card(
            card.id,
            SaveCardRequest(title="Card A", body="Aetheria card body", base_revision=card.revision),
        )

        hits = self._search("aetheria")
        by_kind = {h.kind: h for h in hits if h.field == "body"}

        self.assertIn("research", by_kind)
        self.assertTrue(by_kind["research"].path.startswith("Research / "), by_kind["research"].path)
        self.assertIn("prompt", by_kind)
        self.assertTrue(by_kind["prompt"].path.startswith("Prompt / "), by_kind["prompt"].path)
        self.assertIn("plot", by_kind)
        self.assertTrue(by_kind["plot"].path.startswith("Plot / "), by_kind["plot"].path)


class ChatExclusionTests(SearchCorpusTestCase):
    def test_chats_never_appear_in_hits_or_corpus(self) -> None:
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="Chat"))
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(
                title="Chat",
                messages=[ChatSessionMessage(role="user", content="Aetheria mentioned here")],
            ),
        )

        hits = self._search("aetheria")

        self.assertFalse(any(h.kind == "chat" for h in hits), hits)
        self.assertNotIn(chat.id, self.service._search_corpus())


class InheritedLoreTests(unittest.TestCase):
    """A chain fixture: universe > series > book, mirroring `test_fork_lore.py`'s
    setUp (config_path patched before `declare_full_chain`, which writes the
    machine root through it)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_lore(self, folder: Path, node_id: str, title: str, body: str) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "lore" / f"{node_id}.md", node_id, title, "lore:note", {}, body
        )

    def test_inherited_lore_is_not_owned_owned_root_lore_is(self) -> None:
        self._write_ancestor_lore(self.universe, "ancestor_note", "Ancestor", "Aetheria, long ago")
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Root Note"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(title="Root Note", body="Aetheria, today", base_revision=entry.revision),
        )

        hits = self.service.search(SearchRequest(query="aetheria")).hits
        lore_hits = {h.file_id: h for h in hits if h.kind == "lore"}

        self.assertIn("ancestor_note", lore_hits)
        self.assertFalse(lore_hits["ancestor_note"].owned)
        self.assertIn(entry.id, lore_hits)
        self.assertTrue(lore_hits[entry.id].owned)


class MaintenanceTests(SearchCorpusTestCase):
    def test_save_updates_the_next_query_without_reopen(self) -> None:
        scene_id = self._new_scene("Scene", "Old aetheria text")
        self.assertTrue(self._search("aetheria"))  # builds the corpus

        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(title="Scene", body="New wording entirely", base_revision=current.revision),
        )

        old_hits = [h for h in self._search("aetheria") if h.kind == "manuscript" and h.field == "body"]
        self.assertEqual(old_hits, [])
        new_hits = [h for h in self._search("wording") if h.kind == "manuscript" and h.field == "body"]
        self.assertEqual(len(new_hits), 1, new_hits)
        scene_path = self.service._path_for_node_id(scene_id, "manuscript")
        self.assertEqual(new_hits[0].revision, self.service._revision(scene_path))

    def test_delete_removes_it_from_the_next_query(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria text")
        self.assertTrue(self._search("aetheria"))  # builds the corpus

        self.service.delete_scene(scene_id)

        hits = [h for h in self._search("aetheria") if h.file_id == scene_id]
        self.assertEqual(hits, [])

    def test_rename_keeps_the_id_and_updates_display_path(self) -> None:
        scene_id = self._new_scene("Old Title", "Aetheria stays here")
        self.assertTrue(self._search("aetheria"))  # builds the corpus

        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(title="New Title", body="Aetheria stays here", base_revision=current.revision),
        )

        hits = [h for h in self._search("aetheria") if h.field == "body"]
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0].file_id, scene_id)

    def test_schema_write_invalidates_the_corpus(self) -> None:
        self._new_scene("Scene", "Aetheria text")
        self.assertTrue(self._search("aetheria"))  # builds the corpus
        self.assertIsNotNone(search_corpus.peek(self.root.resolve()))

        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="notes",
                field=MetadataFieldDefinition(name="Notes", type="text"),
                entry_type="manuscript:scene",
            )
        )

        self.assertIsNone(search_corpus.peek(self.root.resolve()))
        hits = [h for h in self._search("aetheria") if h.field == "body"]
        self.assertEqual(len(hits), 1, hits)


class ColdBuildReadCountTests(SearchCorpusTestCase):
    def test_cold_build_reads_each_non_chat_node_once(self) -> None:
        for index in range(3):
            self._new_scene(f"Scene {index}", "Nothing to find here")
        for index in range(2):
            self._new_lore(f"Lore {index}", "Nothing to find here either")
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="Chat"))
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(
                title="Chat", messages=[ChatSessionMessage(role="user", content="irrelevant")]
            ),
        )

        search_corpus.drop()
        node_index_gate.invalidate()

        calls = 0
        original = ProjectService._read_markdown_with_front_matter

        def counting(self, path, *, strict=False, _original=original):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return _original(self, path, strict=strict)

        ProjectService._read_markdown_with_front_matter = counting  # type: ignore[assignment]
        try:
            # A query that matches nothing — only the read count matters here.
            self.service.search(SearchRequest(query="no-such-text-anywhere"))
        finally:
            ProjectService._read_markdown_with_front_matter = original  # type: ignore[assignment]

        # The node index build itself reads front matter through a different
        # helper (`_read_front_matter_only`), so every call counted above
        # belongs to the corpus build alone. Compare against the corpus that
        # build actually produced rather than a hand-counted "3 scenes + 2
        # lore" total, since the index's `by_id` also carries whatever the
        # machine/Library layers contribute (assistants, built-in prompts and
        # plot templates) — all of it is a non-chat node the corpus build
        # reads exactly once too.
        corpus = search_corpus.peek(self.root.resolve())
        self.assertIsNotNone(corpus)
        self.assertGreater(len(corpus), 0, "the corpus under measurement did not actually build")
        self.assertGreater(calls, 0, "the patch never intercepted a read")
        self.assertEqual(calls, len(corpus))
        self.assertNotIn(chat.id, corpus)


class NoRglobGuardTests(unittest.TestCase):
    def test_search_py_has_no_rglob(self) -> None:
        path = PROJECT_SERVICE_DIR / "search.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "rglob"
        ]
        self.assertEqual(offenders, [], f"search.py must read the corpus, never rglob: {offenders}")


class PublishedDictIsImmutableTests(unittest.TestCase):
    """`peek` hands a search the held dict; a save patching the corpus from
    another request worker must not mutate that dict under the iterating
    search (ResolvedIndex's immutable-after-publication idiom)."""

    def _entry(self, node_id: str, name: str) -> CorpusEntry:
        return CorpusEntry(
            id=node_id, kind="lore", entry_type="lore:note", title=name,
            path=Path(f"/x/{name}.md"), layer_id="L", owned=True,
            body=f"body of {name}", metadata_values=(), revision="r1",
        )

    def test_upsert_and_drop_publish_new_dicts(self) -> None:
        corpus = SearchCorpus()
        root = Path("/x")
        corpus.publish(root, [self._entry("a", "alpha"), self._entry("b", "beta")])
        seen = corpus.peek(root)
        self.assertEqual(len(seen), 2)
        corpus.upsert(root, self._entry("c", "gamma"))
        self.assertEqual(len(seen), 2, "the dict a reader holds must not grow under it")
        self.assertEqual(len(corpus.peek(root)), 3)
        corpus.drop_path(Path("/x/alpha.md"))
        self.assertEqual(len(seen), 2, "nor shrink")
        self.assertEqual(set(corpus.peek(root)), {"b", "c"})
        # Iterating the snapshot while patching never raises.
        snapshot = corpus.peek(root)
        for _ in snapshot:
            corpus.upsert(root, self._entry("d", "delta"))
        self.assertEqual(set(corpus.peek(root)), {"b", "c", "d"})


if __name__ == "__main__":
    unittest.main()
