"""Phase 3b-ii/iii: read_node / save_node / delete_node dispatchers
resolve kind via the node index and route to the right per-kind
methods. read_node covers every readable kind (scene, lore, prompt,
assistant, chat, view, plot card/plotline/template); save/delete cover
their indexed kinds — project is singleton and not routed through these
unified entrypoints."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    AssistantEntry,
    CardEntry,
    CharacterArcEntry,
    ChatSession,
    CreateAssistantEntryRequest,
    CreateCardRequest,
    CreateChatSessionRequest,
    CreatePlotlineRequest,
    CreatePlotTemplateRequest,
    EntryTypeDefinition,
    LoreEntry,
    PlotlineEntry,
    PlotTemplate,
    PromptEntry,
    SaveAssistantEntryRequest,
    SaveCardRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    Scene,
    UpsertMetadataEntryTypeRequest,
)
from app.models_views import CreateViewRequest, SaveViewRequest, ViewNode, ViewSpec
from app.services.project_service import ProjectServiceError


class ReadNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Read Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_scene_reader(self) -> None:
        structure = self.service.read_structure()
        # The default project has a starter scene.
        scene_id = structure.root.children[0].scene_id
        self.assertIsNotNone(scene_id)
        result = self.service.read_node(scene_id)
        self.assertIsInstance(result, Scene)
        self.assertEqual(result.id, scene_id)

    def test_dispatches_to_lore_reader(self) -> None:
        created = self.service.create_lore_entry(
            from_request_or_kwargs(title="Test Character", entry_type="lore:note")
        )
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, LoreEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_prompt_reader(self) -> None:
        created = self.service.create_prompt_entry(
            from_request_or_kwargs(title="Test Prompt", entry_type="prompt:general")
        )
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, PromptEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_assistant_reader(self) -> None:
        # Build our own fixture rather than depending on machine state: the
        # conftest autouse fixture isolates the machine config dir per-test, so
        # a default create lands on that (temp) machine layer.
        created = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title="Test Assistant")
        )
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, AssistantEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_chat_reader(self) -> None:
        created = self.service.create_chat_session(
            CreateChatSessionRequest(title="Test Chat")
        )
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, ChatSession)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_plot_card_reader(self) -> None:
        # #1243: plot nodes read through their per-entry_type readers, not
        # read_lore_entry. Before the fix, `plot` fell through to a 422 and
        # `use(card)` silently delivered nothing.
        created = self.service.create_card(CreateCardRequest(title="A Card"))
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, CardEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_plotline_reader(self) -> None:
        created = self.service.create_plotline(CreatePlotlineRequest(title="A Thread"))
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, PlotlineEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_character_arc_reader(self) -> None:
        # ADR-0080: a plot:character_arc is a plot:thread SIBLING of the plotline,
        # so _read_plot_node needs its own branch — a bare is-a-plotline test would
        # miss it and 422, leaving entry()/use() unable to pull an arc into context.
        created = self.service.instantiate_plot_template("builtin-plot-positive-character-change-arc")
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, CharacterArcEntry)
        self.assertEqual(result.id, created.id)

    def test_dispatches_to_plot_template_reader(self) -> None:
        created = self.service.create_plot_template(
            CreatePlotTemplateRequest(title="A Template")
        )
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, PlotTemplate)
        self.assertEqual(result.id, created.id)

    def test_dispatches_a_plot_card_subtype_by_is_a(self) -> None:
        # A user can define a sub-type of plot:card (the layered schema + the
        # readers' is-a family guard both allow it). read_node must dispatch it
        # to read_card by is-a, not exact match — else use() would silently
        # skip subtyped cards, reintroducing the #1243 no-op for them.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="plot:card:romance",
                entry_type=EntryTypeDefinition(
                    name="Romance Card", kind="plot", parent="plot:card"
                ),
                allow_existing=False,
            )
        )
        created = self.service.create_card(
            CreateCardRequest(title="A Tryst", entry_type="plot:card:romance")
        )
        self.assertEqual(created.entry_type, "plot:card:romance")
        result = self.service.read_node(created.id)
        self.assertIsInstance(result, CardEntry)
        self.assertEqual(result.id, created.id)

    def test_plot_card_delivers_its_fields_through_the_lore_block(self) -> None:
        # The regression the issue names: `use(card)` records a selection, the
        # send-path renders it via `_format_lore_block` → read_node. With the
        # plot kind unhandled the node was skipped and the block came back
        # empty; now the card renders as any other node does.
        from app.services.ai.lore_block import _format_lore_block

        card = self.service.create_card(CreateCardRequest(title="They Meet"))
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title="They Meet", body="She spills his coffee.", metadata={}
            ),
        )
        block = _format_lore_block(self.service, [card.id])
        self.assertIn("<card", block)  # tag is the entry_type's bare local key
        self.assertIn('name="They Meet"', block)
        self.assertIn("She spills his coffee.", block)  # the synopsis (body)

    def test_unknown_node_id_raises_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.read_node("scene_does_not_exist")
        self.assertEqual(ctx.exception.status_code, 404)


class SaveNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Save Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_chat_saver(self) -> None:
        created = self.service.create_chat_session(
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
        result = self.service.save_node(created.id, request)
        self.assertIsInstance(result, ChatSession)
        self.assertEqual(result.title, "Renamed via unified path")

    # The remaining kinds exercise every `_SAVE_NODE_DISPATCH` entry end-to-end
    # (#76): the table dispatches by a saver *method name* resolved with getattr,
    # so a stale name or a mis-paired (kind → saver) row would only surface at
    # runtime. These pin each kind's happy path, mirroring ReadNodeDispatchTests.
    def test_dispatches_to_scene_saver(self) -> None:
        scene_id = self.service.read_structure().root.children[0].scene_id
        result = self.service.save_node(
            scene_id, SaveSceneRequest(title="Renamed scene", body="new body")
        )
        self.assertIsInstance(result, Scene)
        self.assertEqual(result.title, "Renamed scene")

    def test_dispatches_to_lore_saver(self) -> None:
        created = self.service.create_lore_entry(
            from_request_or_kwargs(title="A note", entry_type="lore:note")
        )
        result = self.service.save_node(
            created.id, SaveLoreEntryRequest(title="Renamed note", body="")
        )
        self.assertIsInstance(result, LoreEntry)
        self.assertEqual(result.title, "Renamed note")

    def test_dispatches_to_prompt_saver(self) -> None:
        created = self.service.create_prompt_entry(
            from_request_or_kwargs(title="A prompt", entry_type="prompt:general")
        )
        result = self.service.save_node(
            created.id,
            SavePromptEntryRequest(
                title="Renamed prompt", body="", entry_type="prompt:general"
            ),
        )
        self.assertIsInstance(result, PromptEntry)
        self.assertEqual(result.title, "Renamed prompt")

    def test_dispatches_to_assistant_saver(self) -> None:
        created = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title="An assistant")
        )
        result = self.service.save_node(
            created.id, SaveAssistantEntryRequest(title="Renamed assistant")
        )
        self.assertIsInstance(result, AssistantEntry)
        self.assertEqual(result.title, "Renamed assistant")

    def test_dispatches_to_view_saver(self) -> None:
        created = self.service.create_view(
            CreateViewRequest(
                title="A view",
                spec=ViewSpec(kind="lore", expr={"type": "lore:character"}),
            )
        )
        result = self.service.save_node(
            created.id,
            SaveViewRequest(
                title="Renamed view",
                spec=ViewSpec(kind="lore", expr={"type": "lore:location"}),
            ),
        )
        self.assertIsInstance(result, ViewNode)
        self.assertEqual(result.title, "Renamed view")

    def test_wrong_request_type_for_kind_is_422(self) -> None:
        # Create a chat, then try to save it via a Lore request.
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="Wrong-type Test")
        )
        bogus = SaveLoreEntryRequest(
            title="Lore-shape on a chat",
            entry_type="lore:note",
            metadata={},
            body="",
            base_revision="",
        )
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_node(chat.id, bogus)
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
            self.service.save_node("prompt_does_not_exist", request)
        self.assertEqual(ctx.exception.status_code, 404)


class DeleteNodeDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Delete Node Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dispatches_to_chat_deleter(self) -> None:
        created = self.service.create_chat_session(
            CreateChatSessionRequest(title="Delete Chat Test")
        )
        chat_path = self.root / "chats" / f"{created.id}.md"
        self.assertTrue(chat_path.exists())
        result = self.service.delete_node(created.id)
        self.assertIsNone(result)
        self.assertFalse(chat_path.exists())

    def test_dispatches_to_lore_deleter(self) -> None:
        created = self.service.create_lore_entry(
            from_request_or_kwargs(title="Doomed", entry_type="lore:note")
        )
        before = {e.id for e in self.service.list_lore_entries().entries}
        self.assertIn(created.id, before)
        self.service.delete_node(created.id)
        after = {e.id for e in self.service.list_lore_entries().entries}
        self.assertNotIn(created.id, after)

    def test_unknown_node_id_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_node("scene_nothing")
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
    if et in {"lore:note", "lore:character", "lore:location", "lore:item", "lore:base"}:
        return CreateLoreEntryRequest(**kwargs)
    return CreatePromptEntryRequest(**kwargs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
