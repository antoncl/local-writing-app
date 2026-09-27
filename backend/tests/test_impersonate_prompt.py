"""#2298: the built-in `Impersonate` prompt renders the character's metadata
fields (not just title/body) into the system message, read as-of the chat's
anchor scene, plus the optional "Relevant lore" picker.

Renders the SHIPPED `impersonate.md` body (via `read_prompt_entry` + the real
preview path) rather than a hand-copied template, so a template edit that
breaks the feature fails here."""

from __future__ import annotations

from _builtins import builtin_prompt_id
from test_ai_helpers import _HelperFixtureBase

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.preview import PreviewRequest, build_preview


class ImpersonateFieldsTests(_HelperFixtureBase):
    def setUp(self) -> None:
        super().setUp()
        self.impersonate_id = builtin_prompt_id(self.service, "Impersonate")
        self.body = self.service.read_prompt_entry(self.impersonate_id).body

        # A derived character sub-type (is_a lore:character) with one extra
        # field, so the render exercises both an INHERITED field (role, off
        # lore:character) and a DERIVED one (signature_move, off the sub-type).
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["signature_move"] = {"name": "Signature move", "type": "text"}
        data["entry_types"]["lore:character:duelist"] = {
            "name": "Duelist",
            "kind": "lore",
            "parent": "lore:character",
            "fields": ["signature_move"],
        }
        self.service._write_yaml(schema_path, data)

        created = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Zorro", entry_type="lore:character:duelist")
        )
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title="Zorro",
                body="A masked avenger.",
                base_revision=created.revision,
                entry_type="lore:character:duelist",
                metadata={
                    "aliases": [],
                    "role": "protagonist",
                    "signature_move": "A carved Z",
                },
            ),
        )
        self.zorro = self.service.read_lore_entry(created.id)

    def _render(self, *, entry_id: str, as_of: str = "", lore: list | None = None) -> str:
        inputs: dict = {"entry": entry_id, "as_of": as_of}
        if lore is not None:
            inputs["lore"] = lore
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.body,
                target_scene_id="",
                session_id=None,
                inputs=inputs,
                text_before="",
                text_after="",
                commit=False,
                subject=entry_id,
            ),
        )
        return "\n".join(m.text for m in rendered.messages), rendered

    def test_inherited_and_derived_fields_render_under_details(self) -> None:
        text, _ = self._render(entry_id=self.zorro.id)
        self.assertIn("## Details", text)
        self.assertIn("Role: protagonist", text)
        self.assertIn("Signature move: A carved Z", text)

    def test_title_and_body_are_not_duplicated_under_details(self) -> None:
        text, _ = self._render(entry_id=self.zorro.id)
        details = text.split("## Details", 1)[1]
        self.assertNotIn("Name:", details)
        self.assertNotIn("A masked avenger.", details)

    def test_empty_fields_are_omitted(self) -> None:
        # Honor's `home_place` is None and `related_entries`/`pronouns` are unset
        # — none of those labels should appear.
        text, _ = self._render(entry_id=self.honor["id"])
        self.assertNotIn("Home place:", text)
        self.assertNotIn("Pronouns:", text)

    def test_no_stray_blank_lines_in_details(self) -> None:
        text, _ = self._render(entry_id=self.zorro.id)
        details = text.split("## Details", 1)[1].split("## ", 1)[0]
        lines = [line for line in details.split("\n") if line.strip() != ""]
        # Every non-empty line under Details is a "- Label: value" bullet.
        for line in lines:
            self.assertTrue(line.strip().startswith("- "), line)

    def test_as_of_anchor_overlays_a_mutated_field(self) -> None:
        # Mutate Honor's role in scene two; role reads the overlay as-of that
        # scene, and the book-start value elsewhere.
        self._update_scene_with_mutations(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                f"<!-- mutate:entity={self.honor['id']};field=role;"
                "value=antagonist;id=m1 -->"
            ),
        )
        text_before, _ = self._render(entry_id=self.honor["id"])
        self.assertNotIn("Role:", text_before)
        text_after, _ = self._render(
            entry_id=self.honor["id"], as_of=self.scene_two_node.scene_id
        )
        self.assertIn("Role: antagonist", text_after)

    def test_relevant_lore_include_places_the_picked_entry(self) -> None:
        _, rendered = self._render(entry_id=self.honor["id"], lore=[self.manticore["id"]])
        self.assertIn(self.manticore["id"], rendered.used_node_ids)
