"""#2384: a node read BY NAME resolves its own properties, as a dot does.

Jinja's attribute filters (`map(attribute=...)`, `sort(attribute=...)`,
`selectattr`) look an attribute up by subscript first and only fall back to
getattr on an error. `EntryRef.__getitem__` used to go straight to metadata, so
`node["title"]` — and with it the idiomatic `refs | map(attribute="title")` —
rendered None without a warning. These tests render real templates over an
`entity_ref_list` to pin every filter shape a prompt author reaches for."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template


class EntryRefSubscriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(root, "Entry Ref Subscript Tests")
        self.zara = self._character("Zara")
        self.bram = self._character("Bram")
        self.hero = self._character(
            "Seren", metadata={"related_entries": [self.zara, self.bram]}
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _character(self, title: str, metadata: dict | None = None) -> str:
        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        )
        if metadata:
            self.service.save_lore_entry(
                created.id,
                SaveLoreEntryRequest(
                    title=title,
                    entry_type="lore:character",
                    body="",
                    base_revision=created.revision,
                    metadata=metadata,
                ),
            )
        return created.id

    def _render(self, body: str) -> str:
        env = create_environment_for_project(self.service)
        template = '{% set e = entry(hero) %}{% role "system" %}' + body + "{% endrole %}"
        return render_template(template, context={"hero": self.hero}, env=env).messages[0].text

    def test_subscript_reads_the_nodes_own_properties(self) -> None:
        text = self._render('{{ e["title"] }}|{{ e["id"] }}|{{ e["entry_type"] }}')
        self.assertEqual(text.strip(), f"Seren|{self.hero}|lore:character")

    def test_map_attribute_title_names_a_reference_list(self) -> None:
        text = self._render('{{ e.related_entries | map(attribute="title") | join(", ") }}')
        self.assertEqual(text.strip(), "Zara, Bram")

    def test_sort_by_title_keeps_the_ids(self) -> None:
        text = self._render(
            '{{ e.related_entries | sort(attribute="title") | map(attribute="id") | join(",") }}'
        )
        self.assertEqual(text.strip(), f"{self.bram},{self.zara}")

    def test_selectattr_filters_on_entry_type(self) -> None:
        text = self._render(
            '{{ e.related_entries | selectattr("entry_type", "equalto", "lore:character")'
            " | list | length }}"
        )
        self.assertEqual(text.strip(), "2")

    def test_subscript_still_reads_metadata_by_name(self) -> None:
        # A metadata field by name is unchanged: the property check only claims
        # the node's own properties.
        text = self._render('{{ e["related_entries"] | length }}')
        self.assertEqual(text.strip(), "2")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
