"""Phase 3b-ii/iii: read_node / save_node / delete_node dispatchers
resolve kind via the node index and route to the right per-kind
methods. Covers all five indexed kinds (scene, lore, prompt,
assistant, chat) — project is singleton and not routed through these
unified entrypoints."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.main import service as global_service
from app.models import (
    AssistantEntry,
    ChatSession,
    CreateChatSessionRequest,
    LoreEntry,
    PromptEntry,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    Scene,
)
from app.services.project_service import ProjectServiceError


class ReadNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Read Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_scene_reader(self) -> None:
        structure = global_service.read_structure()
        # The default project has a starter scene.
        scene_id = structure.root.children[0].scene_id
        self.assertIsNotNone(scene_id)
        result = global_service.read_node(scene_id)
        self.assertIsInstance(result, Scene)
        self.assertEqual(result.id, scene_id)

    def test_dispatches_to_lore_reader(self) -> None:
        created = global_service.create_lore_entry(
            from_request_or_kwargs(title="Test Character", entry_type="lore:lore_note")
        )
        result = global_service.read_node(created.id)
        self.assertIsInstance(result, LoreEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_prompt_reader(self) -> None:
        created = global_service.create_prompt_entry(
            from_request_or_kwargs(title="Test Prompt", entry_type="prompt:general")
        )
        result = global_service.read_node(created.id)
        self.assertIsInstance(result, PromptEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_assistant_reader(self) -> None:
        # Machine-layer assistants are populated by default — find any.
        assistants = global_service.list_assistant_entries().entries
        if not assistants:
            self.skipTest("no assistants registered on this machine")
        result = global_service.read_node(assistants[0].id)
        self.assertIsInstance(result, AssistantEntry)
        self.assertEqual(result.id, assistants[0].id)

    def test_dispatches_to_chat_reader(self) -> None:
        created = global_service.create_chat_session(
            CreateChatSessionRequest(title="Test Chat")
        )
        result = global_service.read_node(created.id)
        self.assertIsInstance(result, ChatSession)
        self.assertEqual(result.id, created.id)

    def test_unknown_node_id_raises_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            global_service.read_node("scene_does_not_exist")
        self.assertEqual(ctx.exception.status_code, 404)


class SaveNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Save Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_chat_saver(self) -> None:
        created = global_service.create_chat_session(
            CreateChatSessionRequest(title="Save Chat Test")
        )
        request = SaveChatSessionRequest(
            title="Renamed via unified path",
            prompt_entry_id=created.prompt_entry_id,
            assistant_id=created.assistant_id,
            system_prompt=created.system_prompt,
            pinned=created.pinned,
            context_items=list(created.context_items),
            messages=list(created.messages),
        )
        result = global_service.save_node(created.id, request)
        self.assertIsInstance(result, ChatSession)
        self.assertEqual(result.title, "Renamed via unified path")

    def test_wrong_request_type_for_kind_is_422(self) -> None:
        # Create a chat, then try to save it via a Lore request.
        chat = global_service.create_chat_session(
            CreateChatSessionRequest(title="Wrong-type Test")
        )
        bogus = SaveLoreEntryRequest(
            title="Lore-shape on a chat",
            entry_type="lore:lore_note",
            metadata={},
            body="",
            base_revision="",
        )
        with self.assertRaises(ProjectServiceError) as ctx:
            global_service.save_node(chat.id, bogus)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_unknown_node_id_is_404(self) -> None:
        request = SavePromptEntryRequest(
            title="Whatever",
            entry_type="prompt:general",
            body="",
            metadata={},
            inputs=[],
            base_revision="",
        )
        with self.assertRaises(ProjectServiceError) as ctx:
            global_service.save_node("prompt_does_not_exist", request)
        self.assertEqual(ctx.exception.status_code, 404)


class DeleteNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Delete Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_chat_deleter(self) -> None:
        created = global_service.create_chat_session(
            CreateChatSessionRequest(title="Delete Chat Test")
        )
        chat_path = self.root / "chats" / f"{created.id}.yaml"
        self.assertTrue(chat_path.exists())
        result = global_service.delete_node(created.id)
        self.assertIsNone(result)
        self.assertFalse(chat_path.exists())

    def test_dispatches_to_lore_deleter(self) -> None:
        created = global_service.create_lore_entry(
            from_request_or_kwargs(title="Doomed", entry_type="lore:lore_note")
        )
        before = {e.id for e in global_service.list_lore_entries().entries}
        self.assertIn(created.id, before)
        global_service.delete_node(created.id)
        after = {e.id for e in global_service.list_lore_entries().entries}
        self.assertNotIn(created.id, after)

    def test_unknown_node_id_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            global_service.delete_node("scene_nothing")
        self.assertEqual(ctx.exception.status_code, 404)


def from_request_or_kwargs(**kwargs):
    """The create_* methods take a Pydantic request model; this helper
    finds the right one by introspection so the test stays terse."""
    from app.models import (
        CreateLoreEntryRequest,
        CreatePromptEntryRequest,
    )

    # Lore + prompt requests have very similar shapes; pick by caller-
    # supplied entry_type hint.
    et = kwargs.get("entry_type", "")
    if et in {"lore:lore_note", "lore:character", "lore:location", "lore:item", "lore:base"}:
        return CreateLoreEntryRequest(**kwargs)
    return CreatePromptEntryRequest(**kwargs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
