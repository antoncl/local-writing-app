"""#2422: `scene_mutations(scene)` and `lore_as_of("start")` — a scene's anchored
mutations as part of a prompt's brief, and lore resolved at the start of the
scene so a draft does not already know how the scene ends."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    UpsertMetadataFieldRequest,
)
from app.services.ai.chat import one_shot_system_blocks
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.preview import PreviewError, PreviewRequest, build_preview
from app.services.project.lore_mutations import START_OF_SCENE


def _define_field(service, field_id: str, field_type: str, name: str) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type),
            entry_type="lore:character",
        )
    )


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Scene Mutations Tests")
        _define_field(self.service, "rank", "text", "Rank")
        _define_field(self.service, "allies", "entity_ref_list", "Allies")
        self.honor = self._character("Honor", {"rank": "Lieutenant"})
        self.mara = self._character("Mara Quinn")
        self.tomas = self._character("Tomas Reyes")
        self.client = TestClient(app)
        self.s1 = self._new_scene("One")
        self.s2 = self._new_scene("Two")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _character(self, title: str, metadata: dict | None = None) -> str:
        entry_id = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        ).id
        if metadata:
            self.service.save_lore_entry(
                entry_id,
                SaveLoreEntryRequest(
                    title=title, body="", entry_type="lore:character", metadata=metadata
                ),
            )
        return entry_id

    def _new_scene(self, title: str) -> str:
        created = self.client.post("/api/scenes", json={"title": title})
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()["id"]

    def _marker(self, entity: str, field: str, value: str, mid: str, op: str = "replace") -> str:
        return f"<!-- mutate:entity={entity};field={field};op={op};value={value};id={mid} -->"


class SceneMutationsHelperTests(_Base):
    def _items(self, scene_id: object) -> list:
        env = create_environment_for_project(self.service)
        return env.globals["scene_mutations"](scene_id)

    def test_items_come_back_in_body_order_with_anchors_and_closes_interleaved(self) -> None:
        ids = save_scenes_with_mutations(
            self.service,
            {
                self.s1: "Earlier. " + self._marker(self.honor, "rank", "Commander", "e1"),
                self.s2: (
                    "A " + self._marker(self.honor, "rank", "Captain", "m1")
                    + " B " + self._marker(self.honor, "allies", self.mara, "m2", op="add")
                    + " C <!-- mutate:close;ref=m1;id=c1 --> D"
                ),
            },
        )
        m1, m2 = ids["m1"][1], ids["m2"][1]
        items = self._items(self.s2)
        self.assertEqual([i.anchor_id for i in items], [m1, m2, "c1"])
        self.assertEqual([i.kind for i in items], ["change", "change", "end"])
        # The "before" of m1 is the EARLIER scene's mutation, not the base value.
        self.assertEqual(items[0].changes, ["Rank: Commander → Captain"])
        self.assertEqual(items[0].target, "Honor")
        self.assertEqual(items[0].text, "Honor — Rank: Commander → Captain")
        # An add line, with the entity ref rendered as the node's title.
        self.assertEqual(items[1].changes, ["Allies: + Mara Quinn"])
        # A close restates the row(s) it ends — the value they set, no before.
        self.assertEqual(items[2].changes, ["Rank: Captain"])
        self.assertEqual(items[2].text, "Honor — no longer: Rank: Captain")
        # Every item carries its target node, usable with `use()`.
        self.assertEqual([i.entity.id for i in items], [self.honor] * 3)

    def test_a_scene_with_no_prior_mutation_takes_its_before_from_the_base_value(self) -> None:
        save_scenes_with_mutations(
            self.service, {self.s2: "A " + self._marker(self.honor, "rank", "Captain", "m1")}
        )
        self.assertEqual(self._items(self.s2)[0].changes, ["Rank: Lieutenant → Captain"])

    def test_an_empty_before_is_omitted_and_remove_has_its_own_sign(self) -> None:
        save_scenes_with_mutations(
            self.service,
            {
                self.s2: (
                    self._marker(self.mara, "rank", "Spy", "m1")
                    + self._marker(self.honor, "allies", self.tomas, "m2", op="remove")
                )
            },
        )
        items = self._items(self.s2)
        self.assertEqual(items[0].changes, ["Rank: Spy"])
        self.assertEqual(items[1].changes, ["Allies: − Tomas Reyes"])

    def test_a_whole_collection_replace_renders_every_id_as_a_title(self) -> None:
        save_scenes_with_mutations(
            self.service,
            {self.s2: self._marker(self.honor, "allies", f"{self.mara},{self.tomas}", "m1")},
        )
        self.assertEqual(
            self._items(self.s2)[0].changes, ["Allies: Mara Quinn, Tomas Reyes"]
        )

    def test_an_anchor_of_an_unusable_set_is_skipped(self) -> None:
        gone = self._character("Gone")
        save_scenes_with_mutations(
            self.service,
            {
                self.s2: (
                    self._marker(gone, "rank", "Ghost", "m1")
                    + self._marker(self.honor, "rank", "Captain", "m2")
                )
            },
        )
        self.service.delete_lore_entry(gone)  # the first set's pin is now dead
        items = self._items(self.s2)
        self.assertEqual([i.target for i in items], ["Honor"])

    def test_no_scene_or_a_non_scene_gives_nothing(self) -> None:
        save_scenes_with_mutations(
            self.service, {self.s2: self._marker(self.honor, "rank", "Captain", "m1")}
        )
        self.assertEqual(self._items(None), [])
        self.assertEqual(self._items(self.honor), [])
        self.assertEqual(self._items("scene_nope"), [])

    def test_the_global_works_inside_a_template(self) -> None:
        save_scenes_with_mutations(
            self.service, {self.s2: self._marker(self.honor, "rank", "Captain", "m1")}
        )
        env = create_environment_for_project(self.service)
        rendered = env.from_string(
            "{% for c in scene_mutations(s) %}[{{ c.anchor_id }}|{{ c.kind }}|{{ c.text }}]{% endfor %}"
        ).render(s=self.s2)
        self.assertIn("|change|Honor — Rank: Lieutenant → Captain]", rendered)


class LoreAsOfTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.s3 = self._new_scene("Three")
        save_scenes_with_mutations(
            self.service,
            {
                self.s1: "Earlier. " + self._marker(self.honor, "rank", "Commander", "e1"),
                # The anchor sits at offset 0: it must NOT be live "at the start".
                self.s2: self._marker(self.honor, "rank", "Captain", "m1") + " Body.",
            },
        )

    def _template(self, call: str) -> str:
        return (
            f'{{% do use("{self.honor}") %}}{{% do {call} %}}'
            '{% role "system" %}Sys.{% endrole %}{% role "user" %}Go.{% endrole %}'
        )

    def _rendered(self, call: str, *, automatic_lore: bool = True):
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self._template(call),
                target_scene_id=self.s2,
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
                automatic_lore=automatic_lore,
            ),
        )
        return rendered

    @staticmethod
    def _preview_lore(rendered) -> str:
        return rendered.send_lore_stable + rendered.send_lore_volatile

    def test_position_zero_would_wrongly_make_an_offset_zero_anchor_live(self) -> None:
        index = self.service.build_mutations_index()
        self.assertEqual(START_OF_SCENE, -1)
        at_zero = self.service.effective_state(self.honor, self.s2, 0, index)
        at_start = self.service.effective_state(self.honor, self.s2, START_OF_SCENE, index)
        self.assertEqual(at_zero, {"rank": "Captain"})
        self.assertEqual(at_start, {"rank": "Commander"})

    def test_a_prompt_without_lore_as_of_resolves_at_the_end_of_the_scene_on_the_preview_path(self) -> None:
        rendered = self._rendered("auto_lore()")
        self.assertIsNone(rendered.lore_position)
        self.assertIn("<rank>Captain</rank>", self._preview_lore(rendered))

    def test_start_shows_the_earlier_change_but_not_the_scenes_own_preview(self) -> None:
        rendered = self._rendered('lore_as_of("start")')
        self.assertEqual(rendered.lore_position, START_OF_SCENE)
        lore = self._preview_lore(rendered)
        self.assertIn("<rank>Commander</rank>", lore)
        self.assertNotIn("Captain", lore)

    def test_start_is_honoured_on_the_one_shot_send_path(self) -> None:
        rendered = self._rendered('lore_as_of("start")', automatic_lore=False)
        sent = "\n".join(b["text"] for b in one_shot_system_blocks("Sys.", rendered) or [])
        self.assertIn("<rank>Commander</rank>", sent)
        self.assertNotIn("Captain", sent)
        plain = self._rendered("auto_lore()", automatic_lore=False)
        sent_plain = "\n".join(b["text"] for b in one_shot_system_blocks("Sys.", plain) or [])
        self.assertIn("<rank>Captain</rank>", sent_plain)

    def test_a_bad_at_value_is_a_template_error(self) -> None:
        with self.assertRaises(PreviewError) as ctx:
            self._rendered('lore_as_of("end")')
        self.assertIn('takes "start"', str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
