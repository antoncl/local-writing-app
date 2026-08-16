"""ADR-0057 §2: the execution-derived lore gate.

The gate is captured from whether `relevant_lore()` actually ran during a
chat's lock render (not a static text-scan, not a user knob) and persisted as
the chat's `lore_enabled`. These tests cover the two ends of that mechanism:

  - `build_preview` flags `lore_invoked` iff the template executed the helper
    (regardless of whether any lore was returned), which the preview route
    surfaces as `lore_enabled`;
  - `ChatSession.lore_enabled` round-trips through save/read, and a save that
    omits it (a per-turn write) preserves the captured value rather than
    clobbering it to the default.

The send-path half (gate off → no lore block; Journey C) lives in
`test_ai_chat.py::ChatEndpointJournalTests`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateChatSessionRequest, SaveChatSessionRequest
from app.services.ai.preview import PreviewRequest, build_preview

_SYS = '{% role "system" %}'
_END = "{% endrole %}"


class BuildPreviewLoreInvokedTests(unittest.TestCase):
    """`build_preview` records whether `relevant_lore()` executed."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Lore Gate")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _render(self, template_source: str):
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=template_source,
                target_scene_id="",
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        return rendered

    def test_lore_invoked_true_when_helper_called(self) -> None:
        rendered = self._render(f"{_SYS}Lore:\n{{{{ relevant_lore() }}}}{_END}")
        self.assertTrue(rendered.lore_invoked)

    def test_lore_invoked_false_when_helper_absent(self) -> None:
        # A deliberately lore-free prompt (Journey C) — the gate must stay off.
        rendered = self._render(f"{_SYS}A pure style pass. No lore.{_END}")
        self.assertFalse(rendered.lore_invoked)

    def test_lore_invoked_tracks_invocation_not_result(self) -> None:
        # No lore exists in the project, so the helper returns "" (and the empty
        # system block renders to nothing) — but the prompt still *called* it, so
        # the chat is lore-enabled and lore added later will flow in. Invocation,
        # not a non-empty result, is the gate.
        rendered = self._render(f"{_SYS}{{{{ relevant_lore() }}}}{_END}")
        self.assertTrue(rendered.lore_invoked)

    def test_helper_behind_an_unfired_conditional_does_not_flag(self) -> None:
        # The reachability point (ADR-0057 anti-goals): a static text-scan would
        # wrongly flag this; execution does not, because the branch never runs.
        rendered = self._render(
            f"{_SYS}{{% if false %}}{{{{ relevant_lore() }}}}{{% endif %}}X{_END}"
        )
        self.assertFalse(rendered.lore_invoked)


class LoreEnabledPersistenceTests(unittest.TestCase):
    """`ChatSession.lore_enabled` round-trips and is preserved across saves."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Lore Gate Persist")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_defaults_false_on_create(self) -> None:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="C", prompt_entry_id="p")
        )
        self.assertFalse(self.service.read_chat_session(chat.id).lore_enabled)

    def test_lock_save_sets_and_read_round_trips(self) -> None:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="C", prompt_entry_id="p")
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="C", prompt_entry_id="p", lore_enabled=True),
        )
        self.assertTrue(self.service.read_chat_session(chat.id).lore_enabled)

    def test_omitting_lore_enabled_preserves_the_captured_value(self) -> None:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="C", prompt_entry_id="p")
        )
        # Lock render captured True.
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="C", prompt_entry_id="p", lore_enabled=True),
        )
        # A later per-turn save (rename) omits lore_enabled → None → preserve.
        self.service.save_chat_session(
            chat.id, SaveChatSessionRequest(title="Renamed", prompt_entry_id="p")
        )
        reread = self.service.read_chat_session(chat.id)
        self.assertEqual(reread.title, "Renamed")
        self.assertTrue(reread.lore_enabled)

    def test_explicit_false_turns_the_gate_off(self) -> None:
        chat = self.service.create_chat_session(
            CreateChatSessionRequest(title="C", prompt_entry_id="p")
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="C", prompt_entry_id="p", lore_enabled=True),
        )
        self.service.save_chat_session(
            chat.id,
            SaveChatSessionRequest(title="C", prompt_entry_id="p", lore_enabled=False),
        )
        self.assertFalse(self.service.read_chat_session(chat.id).lore_enabled)


if __name__ == "__main__":
    unittest.main()
