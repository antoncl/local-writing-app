"""Effective-name-aware implicit-context matcher (#61). A renamed entity is
detected under its **as-of-scene** name: the effective name-set at the resolution
scene drives `_alias_match`, so the old name stops matching after the rename and
the new name starts. Backs the `GET /api/scenes/{id}/effective-names` primitive.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc
from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import _alias_match


class EffectiveNamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "Effective Names Tests")
        self.remus = svc.create_lore_entry(
            CreateLoreEntryRequest(title="Remus", entry_type="character")
        ).id
        self.client = TestClient(app)
        self.s1 = self._new_scene("One", "The village is quiet.")
        # s2 renames Remus mid-scene.
        self.s2 = self._new_scene(
            "Two",
            f"He changed. <!-- mutate:entity={self.remus};field=title;value=The%20Wolf;id=t1 -->",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        scene_id = self.client.post("/api/scenes", json={"title": title}).json()["id"]
        saved = self.client.put(
            f"/api/scenes/{scene_id}", json={"title": title, "body": body}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    # --- effective_names --------------------------------------------------

    def test_effective_names_base_before_rename(self) -> None:
        self.assertEqual(svc.effective_names(self.s1), {self.remus: ["Remus"]})

    def test_effective_names_reflect_rename_at_and_after(self) -> None:
        self.assertEqual(svc.effective_names(self.s2), {self.remus: ["The Wolf"]})

    def test_effective_names_endpoint(self) -> None:
        res = self.client.get(f"/api/scenes/{self.s2}/effective-names")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {self.remus: ["The Wolf"]})

    def test_rename_to_empty_title_does_not_resurface_base_name(self) -> None:
        # Blanking the title is an intentional rename; the base "Remus" must NOT
        # come back via an `or` fallback (#4). An alias keeps the entry in the
        # name-set so we can assert the old title is gone, not just the entry.
        svc.save_lore_entry(
            self.remus,
            SaveLoreEntryRequest(
                title="Remus", body="", entry_type="character",
                metadata={"aliases": ["Grey"]},
            ),
        )
        scene = self._new_scene(
            "Blank",
            f"<!-- mutate:entity={self.remus};field=title;value=;id=b1 -->",
        )
        self.assertEqual(svc.effective_names(scene), {self.remus: ["Grey"]})

    # --- matcher uses effective names -------------------------------------

    def test_new_name_matches_at_rename_scene(self) -> None:
        self.assertEqual(_alias_match(svc, "The Wolf howled", scene=self.s2), {self.remus})

    def test_old_name_does_not_match_after_rename(self) -> None:
        # As of s2 the effective name is "The Wolf" — the old "Remus" is redacted.
        self.assertEqual(_alias_match(svc, "Remus howled", scene=self.s2), set())

    def test_old_name_still_matches_before_rename(self) -> None:
        self.assertEqual(_alias_match(svc, "Remus howled", scene=self.s1), {self.remus})

    def test_base_names_used_without_a_scene(self) -> None:
        # No resolution scene → base names (prior behavior, no regression).
        self.assertEqual(_alias_match(svc, "Remus howled"), {self.remus})
        self.assertEqual(_alias_match(svc, "The Wolf howled"), set())


if __name__ == "__main__":
    unittest.main()
