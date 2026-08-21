"""#784: reason about fields BY their group in a prompt template.

`fields(e)` descriptors carry each field's `group` (its section label — the same
label an L2 group application stamps on its members, or a manual header), and
`field_value(e, f)` reads a field's value by id, so a template can iterate a
group and render its members:

    {% for f in fields(e) if f.group == "GMO" %}
    {{ f.label }}: {{ field_value(e, f) }}
    {% endfor %}

These tests pin the descriptor's `group`, `field_value`'s by-id/by-descriptor
read, the two composed in a real render, and that `use()` delivers a grouped
field's value like any other field."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import (
    _field_value,
    _fields,
    create_environment_for_project,
)
from app.services.ai.lore_block import _format_lore_block
from app.services.ai.templates import render_template


class FieldsGroupExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Fields Group Tests")
        self._add_fields()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add_fields(self) -> None:
        # A grouped field (a manual "GMO" section label — the same shape a group
        # application stamps on its members) and an ungrouped one, on lore:character.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        fields = data.setdefault("fields", {})
        fields["goal"] = {"name": "Goal", "type": "text", "group": "GMO"}
        fields["obstacle"] = {"name": "Obstacle", "type": "text", "group": "GMO"}
        fields["quirk"] = {"name": "Quirk", "type": "text"}
        character = data["entry_types"].get("lore:character") or {}
        own = list(character.get("fields") or [])
        for field_id in ("goal", "obstacle", "quirk"):
            if field_id not in own:
                own.insert(0, field_id)
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
                metadata={"goal": "Slay the wyrm", "obstacle": "Her own fear", "quirk": "Hums"},
            ),
        )
        return created.id

    def test_descriptor_carries_the_group_label(self) -> None:
        schema = self.service.read_metadata_schema()
        roster = _fields(self.service, schema, "lore:character")
        by_id = {f["id"]: f for f in roster}
        # A template can group/filter by this: `if f.group == "GMO"`.
        self.assertEqual(by_id["goal"]["group"], "GMO")
        self.assertEqual(by_id["obstacle"]["group"], "GMO")
        # Ungrouped → None, but the key is ALWAYS present so a template can test
        # `f.group` without hitting StrictUndefined.
        self.assertIn("group", by_id["quirk"])
        self.assertIsNone(by_id["quirk"]["group"])

    def test_field_value_reads_by_id_and_by_descriptor(self) -> None:
        hero = self._make_hero()
        schema = self.service.read_metadata_schema()
        # By bare id...
        self.assertEqual(_field_value(self.service, schema, hero, "goal"), "Slay the wyrm")
        # ...and by a fields() descriptor (so a loop var `f` works directly).
        descriptor = {"id": "obstacle"}
        self.assertEqual(_field_value(self.service, schema, hero, descriptor), "Her own fear")
        # Intrinsics resolve to their top-level values, not a metadata lookup.
        self.assertEqual(_field_value(self.service, schema, hero, "title"), "Seren")
        self.assertEqual(
            str(_field_value(self.service, schema, hero, "body")).strip(), "A knight of renown."
        )

    def test_a_template_iterates_a_group_and_renders_its_values(self) -> None:
        # The headline #784 use case, end to end: group-filter the roster, then
        # read each member's value with field_value — no `.metadata` in sight.
        hero = self._make_hero()
        env = create_environment_for_project(self.service)
        template = (
            '{% role "system" %}'
            "{% for f in fields(hero) if f.group == 'GMO' %}{{ f.label }}={{ field_value(hero, f) }};{% endfor %}"
            "{% endrole %}"
        )
        text = render_template(template, context={"hero": hero}, env=env).messages[0].text
        self.assertIn("Goal=Slay the wyrm;", text)
        self.assertIn("Obstacle=Her own fear;", text)
        self.assertNotIn("Quirk", text)  # ungrouped field is filtered out

    def test_a_group_is_a_nested_accessor_on_the_entry(self) -> None:
        # The ergonomic form: `entry(x).<group>.<member>` — the group by its
        # designed label, each member by its field name (or id). Both the name
        # and the id resolve; an unknown member is None (StrictUndefined-safe).
        hero = self._make_hero()
        env = create_environment_for_project(self.service)
        text = render_template(
            '{% role "system" %}'
            "{{ entry(hero).GMO.Goal }} | {{ entry(hero).GMO.obstacle }} | "
            "{{ entry(hero).GMO.Missing }}"
            "{% endrole %}",
            context={"hero": hero},
            env=env,
        ).messages[0].text
        self.assertIn("Slay the wyrm | Her own fear |", text)  # by name, then by id
        # A field NOT in the group is not reachable through it.
        self.assertNotIn("Hums", text)

    def test_use_delivers_a_grouped_fields_value(self) -> None:
        # use() renders a grouped field like any other field — the values are
        # delivered (a group is a display concern, not a delivery one).
        hero = self._make_hero()
        block = _format_lore_block(self.service, [hero])
        self.assertIn("Slay the wyrm", block)
        self.assertIn("Her own fear", block)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
