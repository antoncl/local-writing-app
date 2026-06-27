"""Slice 5 of docs/research-strategy.md: lore_note → research/note.

POST /api/lore/{id}/move-to-research copies title + body + tags into a
new research note (appended at the research tree root), then deletes
the source lore_note. Aliases / related_entries / context_policy are
intentionally dropped — they're not in the v1 note schema; the
response surfaces them so the UI can warn.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from app.main import app, service as global_service
from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest


class MoveLoreNoteToResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Migration Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_lore_note(
        self,
        *,
        title: str = "Lancashire mills",
        body: str = "Mills employed children from age 8.",
        metadata: dict | None = None,
    ) -> str:
        entry = global_service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore_note")
        )
        # The service.read_lore_entry pulls the current revision.
        current = global_service.read_lore_entry(entry.id)
        global_service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title,
                body_markdown=body,
                base_revision=current.revision,
                entry_type="lore_note",
                metadata=metadata or {},
            ),
        )
        return entry.id

    # --- happy path ----------------------------------------------------------

    def test_move_creates_research_note_and_deletes_lore_source(self) -> None:
        lore_id = self._make_lore_note(metadata={"tags": ["industrial", "labor"]})

        response = self.client.post(f"/api/lore/{lore_id}/move-to-research")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        note_id = body["note_id"]
        self.assertTrue(note_id.startswith("note_"))
        # Tree has the new note appended at root.
        leaf_ids = [c["scene_id"] for c in body["tree"]["root"]["children"]]
        self.assertIn(note_id, leaf_ids)
        # The new note file exists on disk with the body + tags.
        note_files = list((self.root / "research" / "notes").glob("*.md"))
        self.assertEqual(len(note_files), 1)
        content = note_files[0].read_text(encoding="utf-8")
        self.assertIn("title: Lancashire mills", content)
        self.assertIn("entry_type: note", content)
        self.assertIn("- industrial", content)
        self.assertIn("- labor", content)
        self.assertIn("Mills employed children from age 8.", content)
        # The source lore_note file is gone.
        lore_files = [
            p for p in (self.root / "lore").glob("*.md")
        ]
        self.assertEqual(
            [p.read_text(encoding="utf-8") for p in lore_files
             if "Lancashire mills" in p.read_text(encoding="utf-8")],
            [],
        )
        # Refreshed lore list no longer contains the source.
        self.assertNotIn(
            lore_id, [e["id"] for e in body["lore"]["entries"]]
        )

    # --- dropped fields ------------------------------------------------------

    def test_dropped_fields_reported_when_present(self) -> None:
        # Seed with aliases + context_policy — both intentionally dropped.
        lore_id = self._make_lore_note(
            metadata={
                "tags": ["industrial"],
                "aliases": ["Mill towns", "Cotton mills"],
                "context_policy": "manual_only",
            }
        )
        body = self.client.post(
            f"/api/lore/{lore_id}/move-to-research"
        ).json()
        self.assertEqual(sorted(body["dropped_fields"]), ["aliases", "context_policy"])
        # The new note carries tags but neither aliases nor context_policy.
        note_files = list((self.root / "research" / "notes").glob("*.md"))
        content = note_files[0].read_text(encoding="utf-8")
        self.assertIn("- industrial", content)
        self.assertNotIn("aliases", content)
        self.assertNotIn("context_policy", content)

    def test_dropped_fields_empty_when_no_extras(self) -> None:
        lore_id = self._make_lore_note(metadata={"tags": ["a"]})
        body = self.client.post(
            f"/api/lore/{lore_id}/move-to-research"
        ).json()
        self.assertEqual(body["dropped_fields"], [])

    def test_empty_metadata_values_are_not_reported_as_dropped(self) -> None:
        # A lore_note that has aliases=[] should not flag aliases as
        # dropped — there's no data to lose.
        lore_id = self._make_lore_note(
            metadata={"aliases": [], "tags": []}
        )
        body = self.client.post(
            f"/api/lore/{lore_id}/move-to-research"
        ).json()
        self.assertEqual(body["dropped_fields"], [])

    # --- guardrails ----------------------------------------------------------

    def test_404_when_entry_does_not_exist(self) -> None:
        response = self.client.post("/api/lore/lore_missing/move-to-research")
        self.assertEqual(response.status_code, 404, response.text)

    def test_422_when_entry_is_not_a_lore_note(self) -> None:
        entry = global_service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="character")
        )
        response = self.client.post(
            f"/api/lore/{entry.id}/move-to-research"
        )
        self.assertEqual(response.status_code, 422, response.text)
        # The character entry still exists.
        listed = global_service.list_lore_entries()
        self.assertIn(entry.id, [e.id for e in listed.entries])

    # --- body preservation ---------------------------------------------------

    def test_body_round_trips_verbatim(self) -> None:
        body_text = "# Heading\n\nA paragraph with *emphasis* and a list:\n\n- one\n- two\n"
        lore_id = self._make_lore_note(body=body_text, metadata={"tags": []})
        resp = self.client.post(f"/api/lore/{lore_id}/move-to-research").json()
        note_id = resp["note_id"]
        # Read the new note back through the API.
        reread = self.client.get(f"/api/research/notes/{note_id}").json()
        # Save normalizes the trailing newline; strip for comparison.
        self.assertEqual(reread["body_markdown"].rstrip(), body_text.rstrip())

    # --- tree positioning ----------------------------------------------------

    def test_new_note_appended_at_research_root(self) -> None:
        # Pre-seed an existing research note to confirm the migration
        # appends rather than replacing.
        from app.models import CreateStructureNodeRequest

        global_service.create_research_node(
            CreateStructureNodeRequest(title="Existing", entry_type="note")
        )
        lore_id = self._make_lore_note(title="Imported")
        body = self.client.post(
            f"/api/lore/{lore_id}/move-to-research"
        ).json()
        titles = [c["title"] for c in body["tree"]["root"]["children"]]
        self.assertEqual(titles, ["Existing", "Imported"])


if __name__ == "__main__":
    unittest.main()
