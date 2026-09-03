"""ADR-0081 slice 3b — adjacency parity for a reference nested in a group-list.

Slices 1–3a made a nested `entity_ref` member first-class through the integrity,
authoring, and tag-lifecycle passes. These pin the two AI-context *adjacency*
passes that used to stop at the top level (§4): the Jinja wrapper (`entry(x)`)
must wrap a nested ref to an `EntryRef` so a template resolves the target's
fields, and the lore-block renderer must resolve a nested ref's id to the
target's name — parity with a top-level ref's `<field id>Name</field>`.

The promotion adjacency pass is pinned in `test_promote_lore.py` (it reuses that
module's layer-chain fixture).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.lore_block import _format_lore_block
from app.services.ai.templates import render_template


class RefsInGroupsAdjacencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Refs In Groups Adjacency")
        self._add_group_list_field()
        self.sidekick = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Pip", entry_type="lore:character")
        ).id
        self.hero = self._make_hero()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add_group_list_field(self) -> None:
        # A `roster` list whose item_group is a named group with an `entity_ref`
        # member `who` and a scalar `role` — the shape slices 1/2 made authorable
        # (`item_members` is resolver-derived from the group, never inlined).
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["rel"] = {
            "name": "Relationship",
            "members": [
                {"key": "who", "name": "Who", "type": "entity_ref"},
                {"key": "role", "name": "Role", "type": "text"},
            ],
        }
        data.setdefault("fields", {})["roster"] = {
            "name": "Roster",
            "type": "list",
            "item_group": "rel",
        }
        character = data["entry_types"].get("lore:character") or {}
        own = list(character.get("fields") or [])
        if "roster" not in own:
            own.insert(0, "roster")
        character["fields"] = own
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def _make_hero(self) -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title="Seren",
                entry_type="lore:character",
                body="A knight of renown.",
                base_revision=created.revision,
                metadata={"roster": [{"who": self.sidekick, "role": "squire"}]},
            ),
        )
        return created.id

    # --- Pass 1: the Jinja wrapper descends into a group-list ref member ------

    def test_template_resolves_a_nested_ref_to_its_target(self) -> None:
        env = create_environment_for_project(self.service)
        text = render_template(
            '{% role "system" %}'
            "who={{ entry(hero).roster[0].who.title }};"  # nested ref → EntryRef → title
            "str={{ entry(hero).roster[0].who }};"        # bare EntryRef renders as title too
            "role={{ entry(hero).roster[0].role }}"        # non-ref member passes through
            "{% endrole %}",
            context={"hero": self.hero},
            env=env,
        ).messages[0].text
        self.assertIn("who=Pip;", text)
        self.assertIn("str=Pip;", text)
        self.assertIn("role=squire", text)

    # --- Pass 2: the lore block resolves a nested ref id to the target name ----

    def test_lore_block_resolves_a_nested_ref_name(self) -> None:
        block = _format_lore_block(self.service, [self.hero])
        # The target's legible name rides inline...
        self.assertIn("Pip", block)
        # ...alongside its id as the join key (a top-level ref carries both, §4).
        self.assertIn(self.sidekick, block)

    def test_lore_block_keeps_the_ref_joinable_as_id_and_name(self) -> None:
        # The roster renders as a JSON array; the nested ref is a `{"id","name"}`
        # map so the model reads the name AND can join on the id.
        block = _format_lore_block(self.service, [self.hero])
        start = block.index("<roster>") + len("<roster>")
        payload = json.loads(block[start:block.index("</roster>")].strip())
        self.assertEqual(payload[0]["who"], {"id": self.sidekick, "name": "Pip"})
        self.assertEqual(payload[0]["role"], "squire")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
