"""#2490 / ADR-0098: lore-check notes - parsing the model's `{quote, problem,
entry}` list, the `response_format="notes"` mode of the streaming generate
route, and the `lore_named_in(text)` prompt helper that picks what to check
against."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import open_test_project
from test_ai_helpers import _HelperFixtureBase

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateStructureNodeRequest,
    UpdateProjectSettingsRequest,
)
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.line_notes import (
    LINE_NOTES_TRUNCATED_ERROR,
    LINE_NOTES_UNREADABLE_ERROR,
    NOTES_RESPONSE_SCHEMA,
    checked_against,
    parse_line_notes,
    read_line_notes_reply,
)
from app.services.ai.lore_selection import lore_named_in
from app.services.ai.profiles.base import ChatOutcome
from app.services.ai.providers import StreamDelta, StreamDone
from app.services.ai.sessions import default_registry
from app.services.ai.templates import render_template

_NOTE = {"quote": "her green eyes", "problem": "The passage gives green eyes; the entry says grey.", "entry": "lore_a"}
_GOOD = {"notes": [_NOTE]}


class ParseLineNotesTests(unittest.TestCase):
    def test_a_good_reply_parses(self) -> None:
        notes = parse_line_notes(json.dumps(_GOOD))
        self.assertEqual([n.model_dump() for n in notes or []], [_NOTE])

    def test_tolerates_a_fence_and_a_preamble(self) -> None:
        self.assertEqual(len(parse_line_notes("```json\n" + json.dumps(_GOOD) + "\n```") or []), 1)
        self.assertEqual(len(parse_line_notes("Here: " + json.dumps(_GOOD) + " Done.") or []), 1)

    def test_a_missing_closer_is_repaired(self) -> None:
        self.assertEqual(len(parse_line_notes(json.dumps(_GOOD)[:-1]) or []), 1)

    def test_an_empty_list_is_a_valid_answer(self) -> None:
        self.assertEqual(parse_line_notes('{"notes": []}'), [])

    def test_no_notes_list_is_unreadable(self) -> None:
        self.assertIsNone(parse_line_notes("Nothing wrong."))
        self.assertIsNone(parse_line_notes(""))
        self.assertIsNone(parse_line_notes('{"edits": []}'))
        self.assertIsNone(parse_line_notes('{"notes": "none"}'))

    def test_malformed_items_are_skipped(self) -> None:
        raw = json.dumps(
            {
                "notes": [
                    "not an object",
                    {"quote": "", "problem": "p", "entry": "e"},
                    {"quote": 3, "problem": "p", "entry": "e"},
                    {"quote": "q", "problem": "", "entry": "e"},
                    {"quote": "q", "problem": ["p"], "entry": "e"},
                    {"quote": "q", "problem": "p", "entry": ""},
                    {"quote": "q", "problem": "p"},
                    {"quote": "good", "problem": "p", "entry": "e"},
                ]
            }
        )
        notes = parse_line_notes(raw) or []
        self.assertEqual([n.quote for n in notes], ["good"])


class ReadLineNotesReplyTests(unittest.TestCase):
    def test_a_truncated_reply_is_never_trusted(self) -> None:
        notes, dropped, error = read_line_notes_reply(json.dumps(_GOOD), truncated=True, sent_ids={"lore_a"})
        self.assertIsNone(notes)
        self.assertEqual(dropped, 0)
        self.assertEqual(error, LINE_NOTES_TRUNCATED_ERROR)

    def test_an_unreadable_reply_is_an_error(self) -> None:
        notes, _, error = read_line_notes_reply("Sorry.", truncated=False, sent_ids={"lore_a"})
        self.assertIsNone(notes)
        self.assertEqual(error, LINE_NOTES_UNREADABLE_ERROR)

    def test_a_known_entry_is_kept(self) -> None:
        notes, dropped, error = read_line_notes_reply(json.dumps(_GOOD), truncated=False, sent_ids={"lore_a"})
        self.assertEqual([n.entry for n in notes or []], ["lore_a"])
        self.assertEqual(dropped, 0)
        self.assertIsNone(error)

    def test_an_entry_the_run_never_sent_is_dropped_and_counted(self) -> None:
        raw = json.dumps({"notes": [_NOTE, {**_NOTE, "entry": "lore_invented"}]})
        notes, dropped, _ = read_line_notes_reply(raw, truncated=False, sent_ids={"lore_a"})
        self.assertEqual([n.entry for n in notes or []], ["lore_a"])
        self.assertEqual(dropped, 1)

    def test_malformed_items_count_as_dropped(self) -> None:
        raw = json.dumps({"notes": [_NOTE, "junk", {"quote": "q"}]})
        notes, dropped, _ = read_line_notes_reply(raw, truncated=False, sent_ids={"lore_a"})
        self.assertEqual(len(notes or []), 1)
        self.assertEqual(dropped, 2)


class CheckedAgainstTests(unittest.TestCase):
    def test_send_order_deduplicated_named_as_the_model_saw_them(self) -> None:
        # The name is the rendered block's `name=` (the as-of-scene name, e.g.
        # after a renaming mutation), not the stored title; an id with no block
        # falls back to the id.
        rendered = SimpleNamespace(
            send_lore_stable_ids=["lore_b", "lore_a"],
            send_lore_volatile_ids=["lore_a", "lore_gone"],
            send_lore_stable_entries={
                "lore_b": '<character id="lore_b" name="Bram &amp; Son" aliases="B">\n<body>Bram is &lt;tall&gt;.</body>\n</character>',
                "lore_a": "<character id='lore_a' name='Captain \"Aria\" Voss'><body/></character>",
            },
            send_lore_volatile_entries={"lore_a": '<character id="lore_a" name="stale">x</character>'},
        )
        self.assertEqual(
            checked_against(rendered),  # type: ignore[arg-type]
            [
                {"id": "lore_b", "name": "Bram & Son"},
                {"id": "lore_a", "name": 'Captain "Aria" Voss'},
                {"id": "lore_gone", "name": "lore_gone"},
            ],
        )


class GenerateNotesRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Line Notes Tests")
        default_registry.clear()
        self.client = TestClient(app)
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:container")
        s = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Scene", entry_type="manuscript:scene", parent_id=act.id)
        )
        act_after = next(c for c in s.root.children if c.id == act.id)
        self.scene_id = act_after.children[-1].scene_id
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))
        self.ravenmoor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Ravenmoor", entry_type="lore:location", body="A grey town.")
        )
        self.mira = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Mira", entry_type="lore:character", body="Grey-eyed.")
        )

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def _template(self, *ids: str) -> str:
        uses = "".join(f'{{% do use("{i}") %}}' for i in ids)
        return uses + '{% role "user" %}{{ selection }}{% endrole %}'

    def _post_stream(self, chunks: list[str], template: str, *, truncated: bool = False, route: str = "/stream", **extra: object):
        from app.services import machine_settings as ms

        settings = ms.MachineSettings(
            providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
            default_provider="anthropic",
        )
        seen: dict[str, object] = {}

        def _fake_stream(call, **_kwargs):
            seen["call"] = call
            for chunk in chunks:
                yield StreamDelta(text=chunk)
            yield StreamDone(
                provider="anthropic",
                model="m",
                latency_ms=1,
                stop_reason="max_tokens" if truncated else "end_turn",
                truncated=truncated,
            )

        with patch("app.services.machine_settings.load_settings", return_value=settings), patch(
            "app.routers.ai.ai_providers.chat_stream", side_effect=_fake_stream
        ):
            response = self.client.post(
                "/api/ai/generate" + route,
                json={
                    "template_source": template,
                    "target_scene_id": self.scene_id,
                    "selection": "Her green eyes swept Ravenmoor.",
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    **extra,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line) for line in response.text.splitlines() if line], seen["call"]

    def test_done_carries_notes_dropped_and_checked_against(self) -> None:
        good = {"quote": "green eyes", "problem": "Grey, per the entry.", "entry": self.mira.id}
        invented = {"quote": "Ravenmoor", "problem": "Made up.", "entry": "lore_invented"}
        raw = json.dumps({"notes": [good, invented]})
        lines, call = self._post_stream(
            [raw[:25], raw[25:]],
            self._template(self.ravenmoor.id, self.mira.id, self.mira.id),
            response_format="notes",
        )
        done = lines[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["notes"], [good])
        self.assertEqual(done["notes_dropped"], 1)
        names = {c["id"]: c["name"] for c in done["checked_against"]}
        self.assertEqual(names, {self.ravenmoor.id: "Ravenmoor", self.mira.id: "Mira"})
        self.assertEqual(len(done["checked_against"]), 2)  # de-duplicated
        self.assertNotIn("error", done)
        self.assertEqual(call.response_schema, NOTES_RESPONSE_SCHEMA)

    def test_checked_against_is_present_when_there_are_no_notes(self) -> None:
        lines, _ = self._post_stream(['{"notes": []}'], self._template(self.mira.id), response_format="notes")
        self.assertEqual(lines[-1]["notes"], [])
        self.assertEqual(lines[-1]["notes_dropped"], 0)
        self.assertEqual([c["id"] for c in lines[-1]["checked_against"]], [self.mira.id])

    def test_truncated_and_unreadable_replies_carry_the_error(self) -> None:
        template = self._template(self.mira.id)
        lines, _ = self._post_stream([json.dumps(_GOOD)], template, truncated=True, response_format="notes")
        self.assertFalse(lines[-1]["ok"])
        self.assertEqual(lines[-1]["error"], LINE_NOTES_TRUNCATED_ERROR)
        self.assertIsNone(lines[-1]["notes"])
        lines, _ = self._post_stream(["Sorry."], template, response_format="notes")
        self.assertEqual(lines[-1]["error"], LINE_NOTES_UNREADABLE_ERROR)
        self.assertEqual([c["id"] for c in lines[-1]["checked_against"]], [self.mira.id])

    def test_text_format_adds_no_notes_fields(self) -> None:
        lines, call = self._post_stream(["Plain."], self._template(self.mira.id))
        self.assertNotIn("notes", lines[-1])
        self.assertNotIn("checked_against", lines[-1])
        self.assertIsNone(call.response_schema)

    def test_the_non_streaming_route_refuses_notes(self) -> None:
        from app.services import machine_settings as ms

        settings = ms.MachineSettings(
            providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
            default_provider="anthropic",
        )
        with patch("app.services.machine_settings.load_settings", return_value=settings), patch(
            "app.services.ai.profiles.anthropic.AnthropicProfile.chat",
            return_value=ChatOutcome("{}", "end_turn", SimpleNamespace()),
        ) as mock_chat:
            response = self.client.post(
                "/api/ai/generate",
                json={
                    "template_source": self._template(self.mira.id),
                    "target_scene_id": self.scene_id,
                    "selection": "x",
                    "response_format": "notes",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Notes are only served on the streaming route.")
        mock_chat.assert_not_called()


class LoreNamedInTests(_HelperFixtureBase):
    """`lore_named_in(text)`: the entries a passage names, what those link to,
    the scene's own references, and what THOSE link to."""

    def _policy(self, entry: dict, policy: str, **metadata: object) -> None:
        self._update_lore(
            entry["id"],
            entry_type=entry["entry"].entry_type,
            metadata={**entry["entry"].metadata, "context_policy": policy, **metadata},
            body=entry["entry"].body,
        )

    def _named(self, text: str, scene_node=None) -> list[str]:
        scene = self.service.read_scene(scene_node.scene_id) if scene_node is not None else None
        return lore_named_in(self.service, scene, text)

    def test_a_name_in_the_text_is_named(self) -> None:
        self.assertEqual(self._named("The fleet left Manticore at dawn."), [self.manticore["id"]])

    def test_an_alias_in_the_text_is_named(self) -> None:
        self.assertEqual(self._named("Under the Star Kingdom sky."), [self.manticore["id"]])

    def test_nothing_named_is_empty(self) -> None:
        self.assertEqual(self._named("Nobody was mentioned."), [])

    def test_what_a_named_entry_links_to_is_included(self) -> None:
        # Honor -> Nimitz through related_entries; Nimitz is not in the text.
        self.assertEqual(self._named("Honor Harrington stood."), [self.honor["id"], self.nimitz["id"]])

    def test_a_manual_only_or_never_link_is_left_out(self) -> None:
        self._policy(self.nimitz, "manual_only")
        self.assertEqual(self._named("Honor Harrington stood."), [self.honor["id"]])
        self._policy(self.nimitz, "never")
        self.assertEqual(self._named("Honor Harrington stood."), [self.honor["id"]])

    def test_a_manual_only_or_never_entry_in_the_text_is_not_named(self) -> None:
        self._policy(self.manticore, "manual_only")
        self.assertEqual(self._named("The fleet left Manticore."), [])
        self._policy(self.manticore, "never")
        self.assertEqual(self._named("The fleet left Manticore."), [])

    def test_the_scenes_own_references_and_their_links_are_included(self) -> None:
        # scene_two's pov is Honor; the text names nobody. Honor links to Nimitz
        # (#2488: a passage that says "she" still gets the POV's ship / station).
        self.assertEqual(
            self._named("Nobody was mentioned.", self.scene_two_node), [self.honor["id"], self.nimitz["id"]]
        )

    def test_a_manual_only_scene_reference_is_kept_but_a_never_one_is_not(self) -> None:
        self._policy(self.honor, "manual_only")
        # (`_policy` rewrites Honor from her creation snapshot, which predates her
        # link to Nimitz — so only Honor herself is asserted here.)
        self.assertEqual(self._named("Nobody was mentioned.", self.scene_two_node)[:1], [self.honor["id"]])
        self._policy(self.honor, "never")
        self.assertEqual(self._named("Nobody was mentioned.", self.scene_two_node), [])

    def test_a_manual_only_or_never_link_of_a_scene_reference_is_left_out(self) -> None:
        self._policy(self.nimitz, "manual_only")
        self.assertEqual(self._named("Nobody was mentioned.", self.scene_two_node), [self.honor["id"]])
        self._policy(self.nimitz, "never")
        self.assertEqual(self._named("Nobody was mentioned.", self.scene_two_node), [self.honor["id"]])

    def test_no_id_appears_twice(self) -> None:
        # Honor is named by title AND alias, linked-to by nothing, and the scene's pov;
        # Nimitz is named AND linked from Honor.
        ids = self._named("Honor Harrington, the Salamander, and Nimitz.", self.scene_two_node)
        self.assertCountEqual(ids, [self.honor["id"], self.nimitz["id"]])
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_prompt_helper_places_the_named_lore(self) -> None:
        # Through the Jinja global: the render's ambient `scene` is the second arg.
        env = create_environment_for_project(self.service)
        scene = self.service.read_scene(self.scene_two_node.scene_id)
        render_template(
            '{% do use(lore_named_in("They left Manticore.")) %}{% role "user" %}x{% endrole %}',
            context={"scene": scene},
            env=env,
        )
        self.assertEqual(env.used_nodes, [self.manticore["id"], self.honor["id"], self.nimitz["id"]])  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
