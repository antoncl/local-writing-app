"""#2456: a committed scene body gets the scene's mutation pills back.

Draft scene shows each pill to the model as a `⟦id⟧` marker and commits the
prose it writes as the scene's body. The extraction maps the markers back to
the scene's ORIGINAL anchor comments and appends any pill the draft didn't
place, so the proposal reaching review never loses one. `run_chat_turn` is
mocked; the extraction's own placement is what's under test.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project
from test_ai_extraction import _chat_reply

from app.main import app
from app.models import (
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    SaveChatSessionRequest,
)
from app.services.ai.helpers import _fields
from app.services.project.mutation_anchors import pill_comments


class SceneBodyCommitPillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Scene body commit")
        self.client = TestClient(app)
        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:container")
        created = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Promotion", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        self.scene_id = next(
            c for c in created.root.children if c.id == act.id
        ).children[-1].scene_id
        ids = save_scenes_with_mutations(
            self.service,
            {
                self.scene_id: "Old prose. "
                f"<!-- mutate:entity={honor};field=title;value=Captain%20Honor;id=m1 -->"
                " More. "
                f"<!-- mutate:entity={honor};field=title;value=Admiral%20Honor;id=m2 -->",
            },
        )
        self.first = ids["m1"][1]
        self.second = ids["m2"][1]
        self.comments = dict(pill_comments(self.service.read_scene(self.scene_id).body))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _chat(self) -> str:
        """A chat that registered only the scene's body, as Draft scene does."""
        schema = self.service.read_metadata_schema()
        stored = [
            f for f in _fields(self.service, schema, "manuscript:scene")
            if f["proposable"] and f["id"] == "body"
        ]
        session = self.service.create_chat_session(
            CreateChatSessionRequest(title="Draft", system_prompt="S")
        )
        self.service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title=session.title, system_prompt="S", pinned=False,
                context_items=[], messages=[], field_contract_stored=stored,
            ),
        )
        return session.id

    def _extract(self, drafted: str) -> dict:
        reply = _chat_reply(json.dumps({"fields": [{"field": "body", "value": drafted}]}))
        with patch("app.services.ai.extraction.run_chat_turn", new=AsyncMock(return_value=reply)):
            resp = self.client.post(
                f"/api/ai/entry-patch/{self.scene_id}/extract",
                json={
                    "messages": [{"role": "user", "content": "Draft it."}],
                    "assistant_id": None,
                    "chat_id": self._chat(),
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()
        self.assertTrue(result["ok"], result)
        return result["patch"]["body"]

    def test_a_marker_becomes_the_scenes_own_anchor_comment(self) -> None:
        body = self._extract(f"She stood. ⟦{self.first}⟧ The crew cheered. ⟦{self.second}⟧ Done.")
        self.assertNotIn("⟦", body)
        self.assertIn(f"She stood. {self.comments[self.first]} The crew cheered.", body)
        self.assertIn(f"cheered. {self.comments[self.second]} Done.", body)

    def test_a_pill_the_draft_did_not_place_is_appended_not_lost(self) -> None:
        body = self._extract(f"She stood. ⟦{self.first}⟧ Done.")
        self.assertIn(f"She stood. {self.comments[self.first]} Done.", body)
        self.assertTrue(body.rstrip().endswith(self.comments[self.second]))


if __name__ == "__main__":
    unittest.main()
