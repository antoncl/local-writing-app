from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    CreateLoreEntryRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    SearchRequest,
)
from app.services.project_service import ProjectService


class ReferenceResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "test"
        self.service = ProjectService.created_at(self.root, "Test Project")
        declare_full_chain(self.service, self.root, self.base)
        # See MetadataValidationTests for the rationale — home_place is
        # a test-only field on Character.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["home_place"] = {
            "name": "Home Place",
            "type": "entity_ref",
            "target": {"entry_type": "lore:location"},
        }
        character = data["entry_types"].get("lore:character") or {}
        fields = list(character.get("fields") or [])
        if "home_place" not in fields:
            fields.insert(0, "home_place")
            character["fields"] = fields
            data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _first_scene_id(self) -> str:
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        return self.service._read_front_matter_only(first_scene_path, strict=True)["id"]

    def _save_body(self, entry_id: str, body: str) -> None:
        entry = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=body,
                base_revision=entry.revision,
                entry_type=entry.entry_type,
                metadata=entry.metadata,
            ),
        )

    def test_resolve_returns_titles_for_known_ids(self) -> None:
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        taverna = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Taverna", entry_type="lore:location")
        )

        response = self.service.resolve_references([seren.id, taverna.id])

        ids = {candidate.id: candidate for candidate in response.candidates}
        self.assertEqual(ids[seren.id].title, "Seren")
        self.assertEqual(ids[seren.id].entry_type, "lore:character")
        self.assertTrue(ids[seren.id].found)
        self.assertEqual(ids[taverna.id].title, "Taverna")
        self.assertEqual(ids[taverna.id].kind, "lore")

    def test_resolve_marks_unknown_ids_as_not_found(self) -> None:
        response = self.service.resolve_references(["lore_does_not_exist"])

        self.assertEqual(len(response.candidates), 1)
        candidate = response.candidates[0]
        self.assertFalse(candidate.found)
        self.assertEqual(candidate.id, "lore_does_not_exist")

    def test_resolve_includes_body_summary(self) -> None:
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self._save_body(seren.id, "# Seren\n\nA brave caravan guard.\n")

        response = self.service.resolve_references([seren.id])

        self.assertEqual(response.candidates[0].summary, "A brave caravan guard.")

    def test_candidates_filter_by_kind(self) -> None:
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        scene_id = self._first_scene_id()

        response = self.service.list_reference_candidates(kind="lore")

        ids = {candidate.id for candidate in response.candidates}
        self.assertNotIn(scene_id, ids)
        self.assertTrue(
            any(candidate.title == "Seren" for candidate in response.candidates)
        )

    def test_candidates_filter_by_entry_type_with_inheritance(self) -> None:
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Taverna", entry_type="lore:location")
        )

        characters_only = self.service.list_reference_candidates(
            entry_type="lore:character"
        )
        titles = {candidate.title for candidate in characters_only.candidates}
        self.assertEqual(titles, {"Seren"})

        all_lore = self.service.list_reference_candidates(entry_type="lore:base")
        titles = {candidate.title for candidate in all_lore.candidates}
        self.assertEqual(titles, {"Seren", "Taverna"})

    def test_candidates_exclude_id(self) -> None:
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        aren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Aren", entry_type="lore:character")
        )

        response = self.service.list_reference_candidates(
            entry_type="lore:character", exclude_id=seren.id
        )

        ids = {candidate.id for candidate in response.candidates}
        self.assertIn(aren.id, ids)
        self.assertNotIn(seren.id, ids)

    def test_backlinks_finds_references(self) -> None:
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        taverna = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Taverna", entry_type="lore:location")
        )
        self.service.save_lore_entry(
            seren.id,
            SaveLoreEntryRequest(
                title="Seren",
                body=seren.body,
                base_revision=seren.revision,
                entry_type="lore:character",
                metadata={"home_place": taverna.id},
            ),
        )
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="manuscript:scene",
                metadata={"characters": [seren.id], "locations": [taverna.id]},
            ),
        )

        # `_backlinks_to_targets` is the surviving reverse-map consumer — it
        # backs the scene/research delete guards. The per-node `list_backlinks`
        # endpoint was retired in #325 (the frontend has computed backlinks
        # client-side from the reference graph since #203).
        seren_backlinks = self.service._backlinks_to_targets({seren.id})
        self.assertEqual(len(seren_backlinks), 1)
        link = seren_backlinks[0]
        self.assertEqual(link.id, scene_id)
        self.assertEqual(link.field_id, "characters")

        taverna_backlinks = self.service._backlinks_to_targets({taverna.id})
        sources = {(link.id, link.field_id) for link in taverna_backlinks}
        self.assertEqual(sources, {(seren.id, "home_place"), (scene_id, "locations")})

    def test_backlinks_returns_empty_for_unknown_id(self) -> None:
        self.assertEqual(
            self.service._backlinks_to_targets({"lore_does_not_exist"}), []
        )

    def test_search_resolves_reference_titles_in_excerpts(self) -> None:
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="manuscript:scene",
                metadata={"characters": [seren.id]},
            ),
        )

        by_title = self.service.search(SearchRequest(query="Seren"))
        excerpts = [hit.excerpt for hit in by_title.hits if hit.kind == "manuscript"]
        self.assertTrue(any("Seren" in excerpt for excerpt in excerpts))
        self.assertFalse(any(seren.id in excerpt for excerpt in excerpts))

    def test_http_reference_routes(self) -> None:
        from fastapi.testclient import TestClient

        # The routes resolve their project from the wire scope (#413), so point
        # the test client's header at THIS test's project and clear it
        # afterwards (the conftest fixture injects it). The handle the test holds
        # is bound to the same root and never moves.
        from project_fixtures import clear_test_scope, set_test_scope

        from app.main import app

        set_test_scope(ProjectService.opened_at(self.root).scope)
        try:
            client = TestClient(app)
            seren = self.service.create_lore_entry(
                CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
            )

            resolve_response = client.post(
                "/api/references/resolve", json={"ids": [seren.id, "missing"]}
            )
            self.assertEqual(resolve_response.status_code, 200)
            payload = resolve_response.json()
            ids_by = {candidate["id"]: candidate for candidate in payload["candidates"]}
            self.assertEqual(ids_by[seren.id]["title"], "Seren")
            self.assertFalse(ids_by["missing"]["found"])

            candidates_response = client.get(
                "/api/references/candidates", params={"entry_type": "lore:character"}
            )
            self.assertEqual(candidates_response.status_code, 200)
            titles = {
                candidate["title"]
                for candidate in candidates_response.json()["candidates"]
            }
            self.assertIn("Seren", titles)
        finally:
            clear_test_scope()


class LayeredEntryIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore_at(
        self,
        layer_folder: Path,
        entry_id: str,
        title: str,
        entry_type: str = "lore:note",
    ) -> None:
        from app.models import LoreEntry

        (layer_folder / "lore").mkdir(parents=True, exist_ok=True)
        entry = LoreEntry(
            id=entry_id,
            title=title,
            body=f"# {title}",
            revision="",
            entry_type=entry_type,
            metadata={},
        )
        self.service._write_lore_entry_file(
            layer_folder / "lore" / f"{entry_id}.md", entry
        )

    def _write_prompt_at(self, layer_folder: Path, entry_id: str, title: str) -> None:
        (layer_folder / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            layer_folder / "prompts" / f"{entry_id}.md",
            entry_id,
            title,
            "prompt",
            {},
            f"# {title}",
        )

    def test_lore_index_includes_ancestor_entries(self) -> None:
        self._write_lore_at(
            self.universe, "manticore", "Manticore", entry_type="lore:note"
        )
        self._write_lore_at(
            self.series, "honor", "Honor Harrington", entry_type="lore:note"
        )
        self._write_lore_at(self.root, "nimitz", "Nimitz", entry_type="lore:note")

        entries = self.service.list_lore_entries().entries
        ids_by = {entry.id: entry for entry in entries}

        self.assertEqual(ids_by["manticore"].source_layer_label, "honorverse")
        self.assertEqual(ids_by["honor"].source_layer_label, "honor-harrington")
        self.assertEqual(ids_by["nimitz"].source_layer_label, "Book 1")

    def test_prompt_index_includes_ancestor_entries(self) -> None:
        self._write_prompt_at(self.universe, "continue_voice", "Continue in voice")
        self._write_prompt_at(self.root, "book_specific", "Book-specific prompt")

        entries = self.service.list_prompt_entries().entries
        ids = {entry.id for entry in entries}

        self.assertIn("continue_voice", ids)
        self.assertIn("book_specific", ids)

    def test_descendant_wins_on_id_collision_with_warning(self) -> None:
        self._write_lore_at(self.universe, "duplicated", "Universe Version")
        self._write_lore_at(self.root, "duplicated", "Book Version")

        index = self.service._build_node_index()
        entry = index.by_id["duplicated"]

        self.assertEqual(entry.source_layer_label, "Book 1")
        self.assertTrue(any("shadows" in warning for warning in index.warnings))

    def test_scenes_stay_book_scoped(self) -> None:
        (self.universe / "scenes").mkdir(parents=True, exist_ok=True)
        from app.models import Scene

        ancestor_scene = Scene(
            id="ghost_scene",
            title="Should not appear",
            body="",
            revision="",
            status="draft",
            entry_type="manuscript:scene",
            metadata={},
        )
        self.service._write_scene_file(
            self.universe / "scenes" / "ghost_scene.md", ancestor_scene
        )

        index = self.service._build_node_index()

        self.assertNotIn("ghost_scene", index.by_id)

    def test_ancestor_lore_read_carries_source_layer(self) -> None:
        self._write_lore_at(self.universe, "manticore", "Manticore")

        entry = self.service.read_lore_entry("manticore")

        self.assertEqual(entry.title, "Manticore")
        self.assertEqual(entry.source_layer_label, "honorverse")
        self.assertNotEqual(entry.source_layer_id, "")

    def test_reference_candidate_carries_source_layer(self) -> None:
        self._write_lore_at(self.universe, "manticore", "Manticore")

        response = self.service.list_reference_candidates(kind="lore")
        candidate = next(c for c in response.candidates if c.id == "manticore")

        self.assertEqual(candidate.source_layer_label, "honorverse")


if __name__ == "__main__":
    unittest.main()
