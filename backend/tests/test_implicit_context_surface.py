"""ADR-0075 slice 3 (#1495): the backend send path scans a scene's own **prose
surface** — its body + every `long_text` field, NOT single-line `text` fields
or `aliases` — for implicit-context detection, on both the one-shot/preview
path (`_implicit_lore_ids`) and the chat send path (`expand_context`). Both
funnel through the single `_scene_prose_ids` helper, which scans each
field/body text SEPARATELY through `_alias_match` and unions the id sets, so a
multi-word name can't false-match across a field boundary.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    MetadataFieldDefinition,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.services.ai.chat import expand_and_prepare_chat_blocks
from app.services.ai.lore_selection import (
    _alias_match,
    _relevant_lore_ids,
    _scene_prose_ids,
)
from app.services.ai.sessions import default_registry


class _SurfaceFixtureBase(unittest.TestCase):
    """A project with one act + one scene, and helpers to grow the scene's
    schema with a `long_text` / `text` custom field."""

    def setUp(self) -> None:
        default_registry.clear()
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Surface Tests")

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _make_lore(self, title: str, *, entry_type: str = "lore:character", body: str = "") -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type=entry_type)
        )
        existing = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title,
                body=body,
                base_revision=existing.revision,
                entry_type=entry_type,
                metadata={"aliases": []},
            ),
        )
        return created.id

    def _add_scene_field(self, field_id: str, field_type: str) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id=field_id,
                field=MetadataFieldDefinition(name=field_id.title(), type=field_type),
                entry_type="manuscript:scene",
            )
        )

    def _make_scene(self, *, body: str = "", metadata: dict | None = None, subject: str | None = None) -> str:
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:act")
        added = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Scene One", entry_type="manuscript:scene", parent_id=act.id
            )
        )
        scene_node = next(c for c in added.root.children if c.id == act.id).children[-1]
        scene_id = scene_node.scene_id
        existing = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata=metadata or {},
            ),
        )
        return scene_id


class OneShotSurfaceTests(_SurfaceFixtureBase):
    """`_implicit_lore_ids` (via `_relevant_lore_ids(..., "implicit")`) scans
    the scene's body + every long_text field — not just `summary`."""

    def test_body_and_custom_long_text_field_both_detected(self) -> None:
        self._add_scene_field("description", "long_text")
        self._add_scene_field("callsign", "text")
        honor = self._make_lore("Honor Harrington", body="Captain of a ship.")
        manticore = self._make_lore("Manticore", entry_type="lore:location", body="A star system.")
        hidden = self._make_lore("Cassandra Doe", body="A minor character.")

        scene_id = self._make_scene(
            body="Honor Harrington walked onto the bridge.",
            metadata={
                "description": "The fleet made planetfall at Manticore.",
                # Single-line `text` field — must NOT be scanned even though
                # it names a real entity (Cassandra Doe).
                "callsign": "Cassandra Doe is standing watch.",
            },
        )
        scene = self.service.read_scene(scene_id)

        ids = set(_relevant_lore_ids(self.service, scene, "implicit"))
        self.assertIn(honor, ids)  # from the body
        self.assertIn(manticore, ids)  # from the long_text `description` field
        self.assertNotIn(hidden, ids)  # a `text` field is not a detection surface

    def test_name_only_in_summary_still_detected_superset_behavior(self) -> None:
        # `summary` (the old sole surface) is itself a long_text field —
        # still covered, now just one of several.
        honor = self._make_lore("Honor Harrington", body="")
        scene_id = self._make_scene(
            body="", metadata={"summary": "Honor Harrington takes command."}
        )
        scene = self.service.read_scene(scene_id)
        ids = set(_relevant_lore_ids(self.service, scene, "implicit"))
        self.assertIn(honor, ids)


class FieldBoundaryTests(_SurfaceFixtureBase):
    """A multi-word name must not false-match across a field/body boundary —
    the reason `_scene_prose_ids` scans + unions each text separately instead
    of concatenating them."""

    def test_name_split_across_body_and_field_is_not_falsely_joined(self) -> None:
        self._add_scene_field("description", "long_text")
        bob_smith = self._make_lore("Bob Smith", body="A quiet man.")
        scene_id = self._make_scene(
            body="The stranger introduced himself as Bob",
            metadata={"description": "Smith gave a curt nod and said nothing else."},
        )
        scene = self.service.read_scene(scene_id)

        # The real implementation (separate scans, unioned) does NOT detect
        # "Bob Smith" — neither text contains the full name on its own.
        ids = _scene_prose_ids(self.service, scene)
        self.assertNotIn(bob_smith, ids)

        # Proof the boundary matters: naively concatenating the two texts
        # WOULD false-match "Bob Smith" across the join (`[\s-]+` in the
        # compiled name fragment accepts the newline as the separator) —
        # exactly the failure mode `_scene_prose_ids` is built to avoid.
        concatenated_ids = _alias_match(
            self.service, "The stranger introduced himself as Bob\nSmith gave a curt nod.", scene=scene
        )
        self.assertIn(bob_smith, concatenated_ids)


class ChatSendSurfaceTests(_SurfaceFixtureBase):
    """The chat send path (`expand_context`, via `expand_and_prepare_chat_blocks`)
    scans the resolution scene's prose in addition to the composer message,
    and journals scene-prose hits under `source="scene_prose"`."""

    def _make_lore_chat(self, scene_id: str) -> str:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="RP", prompt_entry_id="p", subject=scene_id)
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="RP", prompt_entry_id="p", lore_enabled=True),
        )
        return chat.id

    def test_scene_prose_hits_are_journaled_separately_from_composer_hits(self) -> None:
        self._add_scene_field("description", "long_text")
        honor = self._make_lore("Honor Harrington", body="Captain of a ship.")
        manticore = self._make_lore("Manticore", entry_type="lore:location", body="A star system.")
        nimitz = self._make_lore("Nimitz", body="A treecat.")

        scene_id = self._make_scene(
            body="Honor Harrington walked onto the bridge.",
            metadata={"description": "The fleet made planetfall at Manticore."},
        )
        chat_id = self._make_lore_chat(scene_id)

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            "SYSTEM PROMPT",
            [{"role": "user", "content": "Tell me about Nimitz."}],
        )

        journal = self.service.read_chat_session(chat_id).journal
        by_id = {e.entry_id: e for e in journal}

        self.assertIn(honor, by_id)
        self.assertEqual(by_id[honor].source, "scene_prose")
        self.assertIn(manticore, by_id)
        self.assertEqual(by_id[manticore].source, "scene_prose")
        self.assertIn(nimitz, by_id)
        self.assertEqual(by_id[nimitz].source, "user_message")

    def test_journal_is_append_only_across_turns(self) -> None:
        # Turn 1 detects the scene's body mention; turn 2 (a fresh composer
        # message, no new scene edit) must not drop it — monotonic journal.
        honor = self._make_lore("Honor Harrington", body="Captain of a ship.")
        scene_id = self._make_scene(body="Honor Harrington walked onto the bridge.")
        chat_id = self._make_lore_chat(scene_id)

        expand_and_prepare_chat_blocks(
            self.service, chat_id, "SYS", [{"role": "user", "content": "begin"}]
        )
        turn1_ids = {e.entry_id for e in self.service.read_chat_session(chat_id).journal}
        self.assertIn(honor, turn1_ids)

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            "SYS",
            [
                {"role": "user", "content": "begin"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "continue"},
            ],
        )
        turn2_ids = {e.entry_id for e in self.service.read_chat_session(chat_id).journal}
        self.assertIn(honor, turn2_ids)


if __name__ == "__main__":
    unittest.main()
