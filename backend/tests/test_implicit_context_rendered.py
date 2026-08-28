"""ADR-0075 slice 3b (#1502): the chat send path scans the first-turn
rendered prompt output (`system_prompt` — the fully Jinja-rendered, locked
system prompt) for implicit-context detection, in the SAME `expand_context`
pass as the composer message and the resolution scene's own prose. Hits are
journaled under `source="rendered_prompt"`.

Precedence when an entity appears on more than one surface:
user_message > rendered_prompt > scene_prose. Idempotency across turns is
inherited for free from `expand_context`'s existing journal dedup (`in_scope`)
— the frozen `system_prompt` re-scans on every turn but yields nothing new
once journaled.
"""

from __future__ import annotations

from test_implicit_context_surface import _SurfaceFixtureBase

from app.models import CreateChatSessionRequest, SaveChatSessionRequest
from app.services.ai.chat import expand_and_prepare_chat_blocks


class RenderedPromptSurfaceTests(_SurfaceFixtureBase):
    """The chat send path (`expand_context`, via `expand_and_prepare_chat_blocks`)
    scans the rendered `system_prompt` as a third surface alongside the
    composer message and the resolution scene's own prose."""

    def _make_lore_chat(self, scene_id: str) -> str:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="RP", prompt_entry_id="p", subject=scene_id)
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="RP", prompt_entry_id="p", lore_enabled=True),
        )
        return chat.id

    def test_entity_named_only_in_rendered_prompt_is_journaled(self) -> None:
        nimitz = self._make_lore("Nimitz", body="A treecat.")
        scene_id = self._make_scene(body="The bridge was quiet.")
        chat_id = self._make_lore_chat(scene_id)

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            "You are roleplaying alongside Nimitz, a treecat companion.",
            [{"role": "user", "content": "Let's begin the scene."}],
        )

        journal = self.service.read_chat_session(chat_id).journal
        by_id = {e.entry_id: e for e in journal}
        self.assertIn(nimitz, by_id)
        self.assertEqual(by_id[nimitz].source, "rendered_prompt")

    def test_composer_beats_rendered_prompt(self) -> None:
        honor = self._make_lore("Honor Harrington", body="Captain of a ship.")
        scene_id = self._make_scene(body="The bridge was quiet.")
        chat_id = self._make_lore_chat(scene_id)

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            "You are roleplaying as Honor Harrington.",
            [{"role": "user", "content": "Honor Harrington walks onto the bridge."}],
        )

        journal = self.service.read_chat_session(chat_id).journal
        by_id = {e.entry_id: e for e in journal}
        self.assertIn(honor, by_id)
        self.assertEqual(by_id[honor].source, "user_message")

    def test_rendered_prompt_beats_scene_prose(self) -> None:
        manticore = self._make_lore(
            "Manticore", entry_type="lore:location", body="A star system."
        )
        scene_id = self._make_scene(body="The fleet made planetfall at Manticore.")
        chat_id = self._make_lore_chat(scene_id)

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            "The story is set in the Manticore system.",
            [{"role": "user", "content": "Let's begin the scene."}],
        )

        journal = self.service.read_chat_session(chat_id).journal
        by_id = {e.entry_id: e for e in journal}
        self.assertIn(manticore, by_id)
        self.assertEqual(by_id[manticore].source, "rendered_prompt")

    def test_first_turn_idempotency_no_new_rendered_entry_on_turn_two(self) -> None:
        nimitz = self._make_lore("Nimitz", body="A treecat.")
        scene_id = self._make_scene(body="The bridge was quiet.")
        chat_id = self._make_lore_chat(scene_id)
        system_prompt = "You are roleplaying alongside Nimitz, a treecat companion."

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            system_prompt,
            [{"role": "user", "content": "begin"}],
        )
        turn1_journal = self.service.read_chat_session(chat_id).journal
        turn1_rendered = [e for e in turn1_journal if e.entry_id == nimitz]
        self.assertEqual(len(turn1_rendered), 1)
        self.assertEqual(turn1_rendered[0].source, "rendered_prompt")

        expand_and_prepare_chat_blocks(
            self.service,
            chat_id,
            system_prompt,
            [
                {"role": "user", "content": "begin"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "continue"},
            ],
        )
        turn2_journal = self.service.read_chat_session(chat_id).journal
        turn2_rendered = [e for e in turn2_journal if e.entry_id == nimitz]
        # Still exactly one entry for Nimitz — the second turn's rescan of
        # the same frozen system_prompt adds nothing new (dedup via
        # `in_scope`), and the journal stays append-only.
        self.assertEqual(len(turn2_rendered), 1)
