"""Two kinds of search noise found dogfooding #1869.

#1870: `entry_type` was a searchable metadata value, so a prose query matched
inside the machine identifier ("Er" → `entry_type: prompt:general`). It is
identity, not text the writer wrote, and never replaceable.

#1871: the node index lists every layer's `project.md` (#334) and the corpus
took them all, so hits landed on ANCESTOR projects' nodes — which the open
project cannot open (`FOREIGN_PROJECT_NODE`) and a replace never writes. The
exclusion lives in ONE predicate (`outside_corpus`) that both the cold build
and the write patch apply.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain
from test_search_corpus import SearchCorpusTestCase

from app.models import (
    CreateLoreEntryRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    SearchRequest,
)
from app.services.project.node_index_gate import node_index_gate
from app.services.project.search_corpus_build import outside_corpus
from app.services.project_service import ProjectService


class EntryTypeIsNotSearchableTests(SearchCorpusTestCase):
    def test_a_query_matching_only_the_entry_type_yields_no_hit(self) -> None:
        prompt = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Prompt A", entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            prompt.id,
            SavePromptEntryRequest(
                title="Prompt A", body="a body", base_revision=prompt.revision, entry_type="prompt:general"
            ),
        )
        scene = self.service.create_scene(CreateSceneRequest(title="Arrival"))
        self.service.save_scene(scene.id, SaveSceneRequest(title="Arrival", body="x", base_revision=scene.revision))

        # The FQNs themselves — a plain word like "general" also lives in the
        # built-in Library's plot-template metadata, so it is not a clean probe.
        self.assertEqual(self._search("prompt:general"), [])
        self.assertEqual(self._search("manuscript:scene"), [])

    def test_the_title_still_matches_as_a_metadata_hit(self) -> None:
        prompt = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Prompt Aetheria", entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            prompt.id,
            SavePromptEntryRequest(
                title="Prompt Aetheria", body="a body", base_revision=prompt.revision, entry_type="prompt:general"
            ),
        )

        hits = [h for h in self._search("aetheria") if h.field == "metadata"]

        self.assertEqual([h.excerpt for h in hits], ["title: Prompt Aetheria"])

    def test_no_metadata_hit_ever_carries_an_entry_type_excerpt(self) -> None:
        # The whole corpus, every kind the fixture creates: no `entry_type:` label.
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Note"))
        self.service.save_lore_entry(
            entry.id, SaveLoreEntryRequest(title="Note", body="lore body", base_revision=entry.revision)
        )

        hits = self.service.search(SearchRequest(query="o")).hits  # matches "lore:note", "Note", "lore body"

        self.assertTrue(hits)
        self.assertFalse([h for h in hits if h.excerpt.startswith("entry_type:")], hits)


class AncestorProjectNodeTests(unittest.TestCase):
    """A chain fixture like `InheritedLoreTests`: universe > series > book, with
    the universe a real project whose title carries the query."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        ProjectService.created_at(self.universe, "Aetheria Universe")
        self.service = ProjectService.created_at(self.root, "Book One")
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

    def test_an_ancestor_project_node_is_indexed_but_not_searchable(self) -> None:
        index = self.service._build_node_index(self.root)
        project_nodes = [e for e in index.by_id.values() if e.kind == "project"]
        # The index still lists it (#334 — backlinks address it); the corpus does not.
        self.assertIn("Aetheria Universe", {e.title for e in project_nodes})

        hits = self.service.search(SearchRequest(query="aetheria")).hits

        self.assertEqual(hits, [])

    def test_the_open_projects_own_project_node_still_matches(self) -> None:
        hits = [h for h in self.service.search(SearchRequest(query="book one")).hits if h.kind == "project"]

        self.assertEqual(len(hits), 1, hits)
        self.assertTrue(hits[0].owned)
        self.assertEqual(hits[0].excerpt, "title: Book One")

    def test_the_predicate_is_the_one_both_paths_use(self) -> None:
        index = self.service._build_node_index(self.root)
        root_layer_id = self.service._metadata_schema_layer_id(self.root)
        by_title = {e.title: e for e in index.by_id.values() if e.kind == "project"}

        self.assertTrue(outside_corpus(by_title["Aetheria Universe"], root_layer_id))
        self.assertFalse(outside_corpus(by_title["Book One"], root_layer_id))
