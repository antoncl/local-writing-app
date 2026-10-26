"""The built-in prose prompts rendered through the preview path: Draft scene and
Continue (#2421, #2604), and the shared Prose craft / Character voice / Prose generation
settings snippets they include (ADR-0101 S1, #2619). Split from test_builtin_library.py
when it passed the 1500-line cap."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _builtins import builtin_prompt_id
from project_fixtures import open_test_project


class DraftScenePromptTests(unittest.TestCase):
    """#2421: the built-in Draft scene prompt, rendered through the preview path
    against a small manuscript (act → three scenes) with a lore character."""

    def setUp(self) -> None:
        from app.models import CreateLoreEntryRequest, CreateStructureNodeRequest

        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Draft Scene Tests")
        self.prompt = self.service.read_prompt_entry(
            builtin_prompt_id(self.service, "Draft scene")
        )
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        self.act = next(c for c in structure.root.children if c.type == "manuscript:container")
        self.scene_ids = []
        for title in ("Opening", "Middle", "Ending"):
            created = self.service.create_structure_node(
                CreateStructureNodeRequest(
                    title=title, entry_type="manuscript:scene", parent_id=self.act.id
                )
            )
            act = next(c for c in created.root.children if c.id == self.act.id)
            self.scene_ids.append(act.children[-1].scene_id)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set(
        self, scene_id: str, *, body: str = "", kind: str = "scene", **metadata: object
    ) -> None:
        from app.models import SaveSceneRequest

        existing = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=existing.title,
                body=body,
                base_revision=existing.revision,
                status="draft",
                entry_type=f"manuscript:{kind}",
                metadata=metadata,
            ),
        )

    def _preview(self, scene_id: str, inputs: dict | None = None):
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.prompt.body,
                target_scene_id=scene_id,
                session_id=None,
                # #2456: a scene conversation — the scene is its `entry` pick.
                inputs={"entry": scene_id, **(inputs or {})},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        return "\n".join(m.text for m in rendered.messages)

    def test_draft_scene_is_a_library_prompt(self) -> None:
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertTrue(entries[self.prompt.id].is_library)

    def test_draft_scene_stops_when_the_scene_has_no_summary(self) -> None:
        from app.services.ai.preview import PreviewError

        with self.assertRaises(PreviewError) as ctx:
            self._preview(self.scene_ids[0])
        self.assertEqual(ctx.exception.kind, "stopped")
        self.assertIn("summary", str(ctx.exception))
        self.assertIsNone(ctx.exception.line)

    def test_draft_scene_renders_the_character_voice_rule(self) -> None:
        # #2580: a character's listed pet words read as a checklist; without
        # the rule the drafter put them in nearly every paragraph. It renders
        # with no POV/tense set, unlike "Prose generation settings".
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1])
        self.assertIn("## Character voice", text)

    def test_the_voice_has_a_narrating_and_a_speaking_part(self) -> None:
        # #2625 (ADR-0101 decision 6): the narrating voice holds only for the viewpoint
        # character, the speaking voice for every speaker; a sample is written like,
        # never from (the baseline lifted 7-12-word runs from samples).
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1])
        self.assertIn("**The narrating voice** applies only while that character is the viewpoint", text)
        self.assertIn("**The speaking voice** applies whenever they speak", text)
        self.assertIn("Write like it, never from it", text)
        # The frequency rule (#2580) is kept after the two parts.
        self.assertLess(text.index("**The speaking voice**"), text.index("they are not a quota"))

    # The user guide docs/prose-steering.md names these ten as the prose actions:
    # change it with them.
    PROSE_BUILTINS = {
        "continue.md", "describe.md", "draft-scene.md", "expand.md", "finalize-roleplay.md",
        "line-edit.md", "rephrase.md", "shorten.md", "show-dont-tell.md", "tighten-grammar.md",
    }

    def test_every_prose_writer_includes_the_three_prose_snippets_in_order(self) -> None:
        # #2580 / #2619: Prose craft, Character voice in prose, Prose generation
        # settings, adjacent and in this order (static first, ADR-0084), in
        # every built-in that writes or edits manuscript prose.
        prompts_dir = Path(__file__).resolve().parents[1] / "app" / "builtin_library" / "prompts"
        # Whole lines, so a snippet's own usage comment (indented) doesn't count.
        lines = {p: p.read_text(encoding="utf-8").splitlines()
                 for p in sorted(prompts_dir.glob("*.md"))}
        trio = ['{% include "Prose craft" %}', '{% include "Character voice in prose" %}',
                '{% include "Prose generation settings" %}']
        prose_writers = [p for p, ls in lines.items() if trio[2] in ls]
        self.assertEqual({p.name for p in prose_writers}, self.PROSE_BUILTINS)
        for path in prose_writers:
            with self.subTest(prompt=path.name):
                ls = lines[path]
                i = ls.index(trio[0])
                self.assertEqual(ls[i:i + 3], trio)

    def test_prose_craft_is_static_text(self) -> None:
        # ADR-0101 decision 2: no template logic, so it caches and copies as is.
        path = (Path(__file__).resolve().parents[1] / "app" / "builtin_library" / "prompts"
                / "prose-craft.md")
        body = path.read_text(encoding="utf-8").split("\n---\n", 1)[1]
        body = body.split("#}", 1)[1]  # past the header comment
        self.assertNotIn("{%", body)
        self.assertNotIn("{{", body)
        self.assertIn("## Prose craft", body)


    def test_draft_scene_renders_summary_previous_prose_and_next_summary(self) -> None:
        self._set(self.scene_ids[0],
                  body="She crossed the bridge at dusk\n<!-- mutate:set=ms_1;id=a1 -->\n"
                       "and never looked back.",
                  summary="Honor leaves the station.")
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        self._set(self.scene_ids[2], summary="The fleet jumps to Manticore.")
        text = self._preview(self.scene_ids[1])
        self.assertIn("Honor meets the admiral.", text)
        self.assertIn("never looked back.", text)
        self.assertNotIn("mutate:", text)  # markers are not story text
        self.assertIn("The fleet jumps to Manticore.", text)
        self.assertIn("Honor leaves the station.", text)  # story so far

    def test_draft_scene_without_previous_prose_keeps_the_story_so_far(self) -> None:
        self._set(self.scene_ids[0], body="She crossed the bridge at dusk.",
                  summary="Honor leaves the station.")
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1], {"include_previous_scene": False})
        self.assertNotIn("crossed the bridge", text)
        self.assertNotIn("Where the previous scene left off", text)
        self.assertIn("Honor leaves the station.", text)

    def test_draft_scene_unset_inputs_arrive_as_none_and_keep_their_defaults(self) -> None:
        # #2578: a blank optional input reaches the template as `none`, which
        # Jinja's plain `default()` doesn't replace — Unset must still mean
        # "continue from the previous scene" and "about 1200 words".
        self._set(self.scene_ids[0], body="She crossed the bridge at dusk.",
                  summary="Honor leaves the station.")
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1],
                             {"include_previous_scene": None, "length": None})
        self.assertIn("crossed the bridge", text)
        self.assertIn("about 1200 words", text)
        self.assertNotIn("None", text)

    def _add_scene_design_fields(self) -> None:
        """#2511: the author's own scene fields, as a user schema adds them."""
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {}).update({
            "value_at_stake": {"name": "Value at stake", "type": "text",
                               "description": "The human value this scene turns."},
            "scene_beats": {"name": "Beats", "type": "list", "item_type": "long_text",
                            "description": 'Prefix the beat where the value turns with "TURN:".'},
            "private_note": {"name": "Private note", "type": "text", "ai_proposable": False},
            "charge_in": {"name": "Charge in", "type": "select",
                          "options": [{"value": "pos", "label": "Positive"}, {"value": "neg"}]},
        })
        scene_type = data.setdefault("entry_types", {}).setdefault("manuscript:scene", {})
        scene_type.setdefault("fields", []).extend(
            ["value_at_stake", "scene_beats", "private_note", "charge_in"])
        self.service._write_yaml(schema_path, data)

    def test_draft_scene_sends_every_field_the_author_designed(self) -> None:
        self._add_scene_design_fields()
        self._set(self.scene_ids[0], summary="Honor leaves the station.",
                  dynamics="Honor is curt.", value_at_stake="duty / self",
                  scene_beats=["She packs.", "TURN: She refuses the posting."],
                  private_note="remember to cut this", pov_mode="first", tense="past")
        text = self._preview(self.scene_ids[0])
        self.assertIn("## This scene: Opening\nHonor leaves the station.", text)
        self.assertIn("### Dynamics", text)
        self.assertIn("Honor is curt.", text)
        self.assertIn("### Value at stake", text)
        self.assertIn("_The human value this scene turns._", text)
        self.assertIn("1. She packs.\n2. TURN: She refuses the posting.", text)
        self.assertNotIn("remember to cut this", text)  # not for the AI
        self.assertNotIn("### Tense", text)  # narration is Prose style's, not the brief's
        self.assertNotIn("### Status", text)  # bookkeeping
        self.assertIn("a numbered list is an order to follow", text)
        # Beat lists are one author's design, not every author's (#2513).
        self.assertNotIn("beat", self.prompt.body.lower())

    def test_scene_brief_shows_a_select_by_its_label(self) -> None:
        self._add_scene_design_fields()
        self._set(self.scene_ids[0], summary="Honor leaves the station.", charge_in="pos")
        text = self._preview(self.scene_ids[0])
        self.assertIn("### Charge in\nPositive", text)  # #2513: not the stored "pos"
        self._set(self.scene_ids[0], summary="Honor leaves the station.", charge_in="neg")
        self.assertIn("### Charge in\nneg", self._preview(self.scene_ids[0]))  # no label → value

    def test_scene_brief_shows_list_items_by_label(self) -> None:
        """#2515: a list of selects, and a grouped item's members, by label."""
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["turn"] = {
            "name": "Turn",
            "members": [
                {"key": "who", "name": "Who", "type": "text"},
                {"key": "way", "name": "Direction", "type": "select",
                 "options": [{"value": "up", "label": "Rises"}, {"value": "down", "label": "Falls"}]},
            ],
        }
        data.setdefault("fields", {}).update({
            "moods": {"name": "Moods", "type": "list", "item_type": "select",
                      "options": [{"value": "calm", "label": "Calm"}, {"value": "dread", "label": "Dread"}]},
            "turns": {"name": "Turns", "type": "list", "item_group": "turn"},
        })
        scene_type = data.setdefault("entry_types", {}).setdefault("manuscript:scene", {})
        scene_type.setdefault("fields", []).extend(["moods", "turns"])
        self.service._write_yaml(schema_path, data)
        self._set(self.scene_ids[0], summary="Honor leaves the station.",
                  moods=["dread", "calm"], turns=[{"who": "Honor", "way": "down"}])
        text = self._preview(self.scene_ids[0])
        self.assertIn("### Moods\n1. Dread\n2. Calm", text)
        self.assertIn("### Turns\n1. Who: Honor; Direction: Falls", text)

    def _roleplay_system(self, scene_id: str) -> str:
        from app.services.ai.preview import PreviewRequest, build_preview

        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Roleplay"))
        rendered, _ = build_preview(self.service, PreviewRequest(
            template_source=prompt.body, target_scene_id=scene_id, session_id=None,
            inputs={"character": self.honor.id}, text_before="", text_after="", commit=False))
        return rendered.messages[0].text

    def test_roleplay_tense_is_the_scenes_effective_tense(self) -> None:
        from app.models import SaveProjectNodeRequest

        current = self.service.read_project_node()
        self.service.save_project_node(SaveProjectNodeRequest(
            title=current.title, body="", entry_type=current.entry_type,
            metadata={"tense": "present", "measurement_system": "metric"}))
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        text = self._roleplay_system(self.scene_ids[0])
        self.assertIn("Write the beat in present tense.", text)  # the book's
        self.assertIn("- Measurement system: Metric", text)  # the shared snippet
        self._set(self.act.scene_id, kind="container", tense="past")
        self.assertIn("Write the beat in past tense.", self._roleplay_system(self.scene_ids[0]))

    def test_draft_scene_names_the_pov_character_inherited_from_the_act(self) -> None:
        # #2619: Prose generation settings names the viewpoint character beside
        # the mode and tense (the resolved narration, here inherited from the act).
        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        text = self._preview(self.scene_ids[0])
        self.assertIn("- Point-of-view character: Honor Harrington", text)

    def test_draft_scene_carries_prose_craft_and_keeps_only_its_task_rules(self) -> None:
        """#2619 / ADR-0101: the craft rules live in the Prose craft snippet; the
        prompt keeps the one stretch of time, the markers and the task."""
        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        text = self._preview(self.scene_ids[0])
        self.assertIn("## Prose craft", text)
        self.assertIn("**Viewpoint discipline.**", text)
        self.assertIn("**One continuous stretch of time.**", text)
        for moved in ("**One mind.**", "**Trust the reader.**", "**One narrator.**",
                      "**No one's mind.**", "Keep dialogue tags plain."):
            self.assertNotIn(moved, text)
        self.assertIn("as *Prose craft* below says", text)
        self.assertIn("_This brief is the author's notes on the scene, for you and not the reader", text)
        # Prose style reads the drafted scene's narration, not the editor's
        # scene, so it agrees with the viewpoint (#2604 review).
        self.assertIn("- Narrative POV: Third person — limited", text)
        # Craft first, per-scene settings last (ADR-0084).
        self.assertLess(text.index("## Prose craft"), text.index("## Character voice"))
        self.assertLess(text.index("## Character voice"), text.index("## Prose style"))

    def test_draft_scene_asks_the_model_to_choose_a_viewpoint_only_when_none_is_set(self) -> None:
        rule = "**Choose the viewpoint.**"
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        self.assertIn(rule, self._preview(self.scene_ids[0]))  # no mode, no character
        self._set(self.act.scene_id, kind="container", pov_mode="third_limited")
        self.assertIn(rule, self._preview(self.scene_ids[0]))  # a close mode, no character
        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        self.assertNotIn(rule, self._preview(self.scene_ids[0]))
        self._set(self.act.scene_id, kind="container", pov_mode="third_omniscient")
        self.assertNotIn(rule, self._preview(self.scene_ids[0]))
        self._set(self.act.scene_id, kind="container", pov_mode="third_objective")
        self.assertNotIn(rule, self._preview(self.scene_ids[0]))
        # The old unconditional sentence about the character is gone for good.
        self.assertNotIn("The point-of-view character is **", self._preview(self.scene_ids[0]))

    def test_draft_scene_places_the_viewpoint_character_once(self) -> None:
        # The Character voice snippet places the entry; the prompt no longer does.
        from app.services.ai.chat import one_shot_system_blocks
        from app.services.ai.preview import PreviewRequest, build_preview

        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.prompt.body,
                target_scene_id=self.scene_ids[0],
                session_id=None,
                inputs={"entry": self.scene_ids[0]},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        ids = rendered.send_lore_stable_ids + rendered.send_lore_volatile_ids
        self.assertEqual(ids.count(self.honor.id), 1)
        sent = "\n".join(b["text"] for b in one_shot_system_blocks("Sys.", rendered) or [])
        self.assertEqual(sent.count('name="Honor Harrington"'), 1)

    def _render(self, title: str, scene_id: str, inputs: dict | None = None) -> str:
        from app.services.ai.preview import PreviewRequest, build_preview

        prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, title))
        rendered, _ = build_preview(self.service, PreviewRequest(
            template_source=prompt.body, target_scene_id=scene_id, session_id=None,
            inputs=inputs or {}, text_before="", text_after="", commit=False))
        return "\n".join(m.text for m in rendered.messages)

    def test_finalize_roleplay_names_the_character_inherited_from_the_act(self) -> None:
        # #2619: it reads the resolved narration, where pov(scene) alone would
        # see nothing — the character is set on the act, not the scene.
        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        text = self._render("Finalize roleplay", self.scene_ids[0])
        self.assertIn("Tell it from Honor Harrington's point of view.", text)
        self.assertIn("Prose craft* governs the words you write here", text)
        self.assertIn("- Point-of-view character: Honor Harrington", text)

    def test_prose_craft_keeps_the_naming_and_subtext_rules(self) -> None:
        # #2604's naming rule and the old Trust-the-reader subtext clause moved
        # into Prose craft (#2620 review): without them drafts name strangers early
        # and have characters announce their feelings.
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        text = self._preview(self.scene_ids[0])
        self.assertIn("named only once the scene gives the name", text)
        self.assertIn("Characters rarely say outright what they want or feel either", text)

    def test_finalize_roleplay_keeps_interiority_in_an_omniscient_book(self) -> None:
        # #2620 review: the resolved narration gives an omniscient book no viewpoint
        # character, but its narrator knows every mind — keep their interiority there.
        self._set(self.act.scene_id, kind="container", pov_mode="third_omniscient", pov=self.honor.id)
        text = self._render("Finalize roleplay", self.scene_ids[0])
        self.assertIn("fold their interiority into the narration, moving between minds", text)
        self.assertNotIn("cut all private interiority", text)
        self._set(self.act.scene_id, kind="container", pov_mode="third_objective")
        self.assertIn("cut all private interiority", self._render("Finalize roleplay", self.scene_ids[0]))

    def test_the_lore_prompts_treat_style_notes_as_content(self) -> None:
        # Decision 7: how the book is written is content in a lore entry.
        sentence = "are content here, not instructions: write the entry in this register"
        for title in ("Revise entry", "Follow a change"):
            with self.subTest(prompt=title):
                text = self._render(title, self.scene_ids[0], {"entry": self.honor.id})
                self.assertIn(sentence, text)

    def test_revise_entry_shapes_a_voice_section(self) -> None:
        # #2625 (ADR-0101 decision 7): narrating and speaking voice apart, and a ~150-word
        # sample that is the one part in prose and counts toward the length.
        text = self._render("Revise entry", self.scene_ids[0], {"entry": self.honor.id})
        self.assertIn("When the entry has a voice section, or the author asks for one, write it in three parts", text)
        self.assertIn("**Sample:** about 150 words of prose", text)
        self.assertIn("A narrator with a persona of its own gets only a narrating voice.", text)
        self.assertNotIn("A voice section's shape", text)  # the template comment doesn't render

    def test_revise_entry_offers_no_voice_to_a_location(self) -> None:
        # #2626 review: a location or an item has no voice; the rule stays off it.
        from app.models import CreateLoreEntryRequest

        harbour = self.service.create_lore_entry(CreateLoreEntryRequest(title="The harbour", entry_type="lore:location"))
        text = self._render("Revise entry", self.scene_ids[0], {"entry": harbour.id})
        self.assertNotIn("write it in three parts", text)
        # Create mode asks the type being created (the picker is blank, as the app sends it).
        made = self._render("Revise entry", self.scene_ids[0], {"entry": "[]", "entry_type": "lore:character"})
        self.assertIn("write it in three parts", made)
        made = self._render("Revise entry", self.scene_ids[0], {"entry": "[]", "entry_type": "lore:location"})
        self.assertNotIn("write it in three parts", made)

    def test_draft_scene_lists_the_scenes_anchored_changes_as_its_brief(self) -> None:
        from mutation_helpers import save_scenes_with_mutations

        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        ids = save_scenes_with_mutations(
            self.service,
            {
                self.scene_ids[1]: "Beats. "
                f"<!-- mutate:entity={self.honor.id};field=title;value=Dame%20Honor;id=m1 -->",
            },
        )
        _set_id, anchor_id = ids["m1"]
        text = self._preview(self.scene_ids[1])
        self.assertIn("### Changes this scene makes", text)
        self.assertIn(f"- `⟦{anchor_id}⟧` Honor Harrington — Title: Honor Harrington → Dame Honor", text)
        self.assertIn("apart from the change markers", text)

    def test_draft_scene_places_pov_and_targets_as_picks_at_the_scenes_start(self) -> None:
        from mutation_helpers import save_scenes_with_mutations

        from app.models import CreateLoreEntryRequest
        from app.services.ai.chat import one_shot_system_blocks
        from app.services.ai.preview import PreviewRequest, build_preview

        self._set(self.act.scene_id, kind="container", pov_mode="third_limited", pov=self.honor.id)
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        admiral = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Admiral Courvosier", entry_type="lore:character")
        ).id
        save_scenes_with_mutations(
            self.service,
            {
                self.scene_ids[1]: "Beats. "
                f"<!-- mutate:entity={admiral};field=title;value=Fallen%20Admiral;id=m1 -->",
            },
        )
        for automatic_lore in (False, True):
            rendered, _ = build_preview(
                self.service,
                PreviewRequest(
                    template_source=self.prompt.body,
                    target_scene_id=self.scene_ids[1],
                    session_id=None,
                    inputs={"entry": self.scene_ids[1]},
                    text_before="",
                    text_after="",
                    commit=False,
                    automatic_lore=automatic_lore,
                ),
            )
            sent = "\n".join(b["text"] for b in one_shot_system_blocks("Sys.", rendered) or [])
            self.assertIn('name="Honor Harrington"', sent)  # the POV character
            self.assertIn('name="Admiral Courvosier"', sent)  # the mutation target ...
            self.assertNotIn("Fallen Admiral", sent)  # ... as it stands at the scene's start
            # Draft scene runs no automatic lore, so the estimate shows none.
            self.assertFalse(rendered.lore_invoked)
            self.assertEqual(
                set(rendered.send_lore_stable_ids + rendered.send_lore_volatile_ids),
                {self.honor.id, admiral},
            )

    def test_draft_scene_is_a_scene_conversation_that_commits_the_body(self) -> None:
        # #2456: offered on scenes, committing the body behind a visual diff —
        # not a cursor insert on the Continue shelf.
        entry = {e.id: e for e in self.service.list_prompt_entries().entries}[self.prompt.id]
        self.assertEqual(entry.offer_on, ["manuscript:scene"])
        self.assertEqual(entry.computed_metadata["disposition"], "Revise entities")
        output = self.prompt.context_strategy.output
        self.assertEqual((output.handler, output.commit.review), ("extract_to_node", "visual_diff"))

    def test_draft_scene_shows_existing_prose_to_redraft(self) -> None:
        self._set(self.scene_ids[1], body="Honor waited in the anteroom.",
                  summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1])
        self.assertIn("### The scene as it is written now", text)
        self.assertIn("Honor waited in the anteroom.", text)

    def test_draft_scene_of_an_empty_scene_shows_no_existing_prose(self) -> None:
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        self.assertNotIn("The scene as it is written now", self._preview(self.scene_ids[1]))

    def test_a_scene_holding_only_its_pills_counts_as_empty(self) -> None:
        # Found in the browser: the pills' comments strip to bare whitespace,
        # which must not read as prose to redraft.
        from mutation_helpers import save_scenes_with_mutations

        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        save_scenes_with_mutations(
            self.service,
            {
                self.scene_ids[1]:
                f"<!-- mutate:entity={self.honor.id};field=title;value=Dame%20Honor;id=m1 -->\n\n"
                f"<!-- mutate:entity={self.honor.id};field=title;value=Lady%20Honor;id=m2 -->",
            },
        )
        text = self._preview(self.scene_ids[1])
        self.assertIn("Changes this scene makes", text)
        self.assertNotIn("The scene as it is written now", text)

    def test_the_author_directions_end_before_the_story_so_far(self) -> None:
        # Found in the browser: the snippet's last line ran into the heading.
        self._set(self.scene_ids[0], summary="Honor leaves the station.")
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        self.assertIn("\n\n## The story so far", self._preview(self.scene_ids[1]))

    def test_draft_scene_without_anchors_has_no_changes_section(self) -> None:
        self._set(self.scene_ids[1], summary="Honor meets the admiral.")
        text = self._preview(self.scene_ids[1])
        self.assertNotIn("Changes this scene makes", text)
        self.assertNotIn("⟦", text)


class ContinuePromptTests(unittest.TestCase):
    """#2457: the built-in Continue prompt picks the prose up at the cursor,
    rendered through the preview path against an act with two scenes."""

    def setUp(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Continue Tests")
        self.prompt = self.service.read_prompt_entry(builtin_prompt_id(self.service, "Continue"))
        structure = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:container")
        )
        act = next(c for c in structure.root.children if c.type == "manuscript:container")
        self.act = act
        self.scene_ids = []
        for title in ("Opening", "Middle"):
            created = self.service.create_structure_node(
                CreateStructureNodeRequest(
                    title=title, entry_type="manuscript:scene", parent_id=act.id
                )
            )
            parent = next(c for c in created.root.children if c.id == act.id)
            self.scene_ids.append(parent.children[-1].scene_id)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _summarize(self, scene_id: str, summary: str) -> None:
        from app.models import SaveSceneRequest

        existing = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=existing.title,
                body=existing.body,
                base_revision=existing.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"summary": summary},
            ),
        )

    def _preview(self, text_before: str, text_after: str = "", inputs: dict | None = None):
        from app.services.ai.preview import PreviewRequest, build_preview

        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.prompt.body,
                target_scene_id=self.scene_ids[1],
                session_id=None,
                inputs=inputs or {},
                text_before=text_before,
                text_after=text_after,
                commit=False,
            ),
        )
        return "\n".join(m.text for m in rendered.messages)

    def test_continue_is_a_library_prompt_on_the_continue_shelf(self) -> None:
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertTrue(entries[self.prompt.id].is_library)
        self.assertEqual(entries[self.prompt.id].computed_metadata["disposition"], "Continue")

    def test_continue_stops_without_prose_before_the_cursor(self) -> None:
        from app.services.ai.preview import PreviewError

        with self.assertRaises(PreviewError) as ctx:
            self._preview("<!-- mutate:set=ms_1;id=a1 -->\n  ")
        self.assertEqual(ctx.exception.kind, "stopped")
        self.assertIn("Draft scene", str(ctx.exception))

    def test_continue_quotes_the_text_around_the_cursor_as_story_text(self) -> None:
        text = self._preview(
            "She crossed the bridge\n<!-- mutate:set=ms_1;id=a1 -->\nat dusk and",
            "The admiral was waiting.",
        )
        self.assertIn("at dusk and", text)
        self.assertNotIn("mutate:", text)  # markers are not story text
        self.assertIn("## The text after the cursor", text)
        self.assertIn("The admiral was waiting.", text)

    def test_continue_without_text_after_has_no_after_section(self) -> None:
        text = self._preview("She crossed the bridge at dusk.")
        self.assertNotIn("The text after the cursor", text)

    def test_continue_gives_the_scene_and_story_so_far_and_the_direction(self) -> None:
        self._summarize(self.scene_ids[0], "Honor leaves the station.")
        self._summarize(self.scene_ids[1], "Honor meets the admiral.")
        text = self._preview(
            "She crossed the bridge at dusk.", inputs={"note": "Make it rain.", "length": 150}
        )
        self.assertIn("Honor leaves the station.", text)  # story so far
        self.assertIn("Honor meets the admiral.", text)  # this scene
        self.assertIn("## Direction\nMake it rain.", text)
        self.assertIn("about 150 words", text)

    def test_continue_keeps_only_the_tail_of_a_long_text_before(self) -> None:
        before = " ".join(f"w{i}" for i in range(1000))
        text = self._preview(before)
        self.assertIn("w999", text)
        self.assertNotIn("w100 ", text)


    def _set_act_pov(self, character_id: str) -> None:
        from app.models import SaveSceneRequest

        existing = self.service.read_scene(self.act.scene_id)
        self.service.save_scene(
            self.act.scene_id,
            SaveSceneRequest(
                title=existing.title,
                body=existing.body,
                base_revision=existing.revision,
                status="draft",
                entry_type="manuscript:container",
                metadata={"pov_mode": "third_limited", "pov": character_id},
            ),
        )

    def test_continue_carries_prose_craft_and_names_the_character_in_the_settings(self) -> None:
        from app.models import CreateLoreEntryRequest

        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        self._set_act_pov(honor.id)
        text = self._preview("She crossed the bridge at dusk.")
        self.assertIn("## Prose craft", text)
        self.assertNotIn("The point-of-view character is **", text)
        self.assertIn("- Point-of-view character: Honor Harrington", text)
        self.assertNotIn("do not end on a reflective or summarizing paragraph", text)

    def test_continue_places_the_viewpoint_character_once(self) -> None:
        from app.models import CreateLoreEntryRequest
        from app.services.ai.chat import one_shot_system_blocks
        from app.services.ai.preview import PreviewRequest, build_preview

        honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        self._set_act_pov(honor.id)
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.prompt.body,
                target_scene_id=self.scene_ids[1],
                session_id=None,
                inputs={},
                text_before="She crossed the bridge at dusk.",
                text_after="",
                commit=False,
            ),
        )
        ids = rendered.send_lore_stable_ids + rendered.send_lore_volatile_ids
        self.assertEqual(ids.count(honor.id), 1)
        sent = "\n".join(b["text"] for b in one_shot_system_blocks("Sys.", rendered) or [])
        self.assertEqual(sent.count('name="Honor Harrington"'), 1)


if __name__ == "__main__":
    unittest.main()
