"""AI template helpers that read an entry as of a scene (split from test_ai_helpers.py).

These exercise `entry()` / the ambient scene / impersonate previews against
mutation sets anchored in scenes (ADR-0095)."""
from __future__ import annotations

from test_ai_helpers import _HelperFixtureBase

from app.services.ai.helpers import (
    create_environment_for_project,
)
from app.services.ai.templates import render_template


class EntryAsOfHelperTests(_HelperFixtureBase):
    """ADR-0060 §3 (was ADR-0055 §1): `entry(entry, at=scene)` resolves the subject
    through `effective_state` at the explicit anchor scene; no anchor (`at=""`)
    degrades to a book-start read."""

    def _mutate_honor_in_scene_two(self) -> None:
        from urllib.parse import quote

        new_body = quote("Admiral of the Fleet. Battle-hardened.")
        self._update_scene_with_mutations(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "The fleet returns.", "characters": [], "pov": self.honor["id"]},
            body=(
                "Honor is promoted. "
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=body;value={new_body};id=m2 -->"
            ),
        )

    def _render_as_of(self, scene_id: str) -> str:
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{% set c = entry(who, at=as_of) %}'
            "{{ c.title }}|{{ c.body }}{% endrole %}",
            context={"who": self.honor["id"], "as_of": scene_id},
            env=env,
        )
        # A stored lore body keeps a trailing newline; the value resolved from a
        # marker does not. Strip so the assertions compare content, not storage.
        return out.messages[0].text.strip()

    def test_reads_mutated_state_at_or_after_the_change(self) -> None:
        self._mutate_honor_in_scene_two()
        text = self._render_as_of(self.scene_two_node.scene_id)
        self.assertEqual(text, "Admiral Harrington|Admiral of the Fleet. Battle-hardened.")

    def test_reads_base_state_before_the_change(self) -> None:
        self._mutate_honor_in_scene_two()
        # scene_one precedes scene_two in the manuscript, so the marker is not
        # yet live there — the subject reads at its book-start self.
        text = self._render_as_of(self.scene_one_node.scene_id)
        self.assertEqual(text, "Honor Harrington|Captain of the Fearless. Treecat-adopted.")

    def test_no_anchor_is_a_book_start_read(self) -> None:
        self._mutate_honor_in_scene_two()
        # Empty anchor → exactly `original()` (book-start), even though a
        # mutation exists downstream.
        self.assertEqual(
            self._render_as_of(""),
            "Honor Harrington|Captain of the Fearless. Treecat-adopted.",
        )

    def test_resolves_a_context_pick_scene_value(self) -> None:
        # The anchor input is a scene `context_pick`; when the writer picks in the
        # widget the value is a JSON ref list, not a bare id. It must resolve the
        # same as the bare-id launch seed (ADR-0055 §1).
        import json

        self._mutate_honor_in_scene_two()
        picked = json.dumps([{"id": self.scene_two_node.scene_id, "kind": "manuscript"}])
        self.assertEqual(
            self._render_as_of(picked),
            "Admiral Harrington|Admiral of the Fleet. Battle-hardened.",
        )

    def test_overlays_mutated_metadata_fields_not_just_title_body(self) -> None:
        # Collection (aliases, multi_select) and scalar entity_ref (home_place)
        # mutations must ride the metadata overlay, not only intrinsic title/body.
        self._update_scene_with_mutations(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                f"<!-- mutate:entity={self.honor['id']};field=aliases;op=add;value=Steadholder;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=home_place;value={self.manticore['id']};id=m2 -->"
            ),
        )
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{% set c = entry(who, at=as_of) %}'
            "{{ c.aliases | join(',') }}|{{ c.home_place.title if c.home_place else 'none' }}"
            "{% endrole %}",
            context={"who": self.honor["id"], "as_of": self.scene_two_node.scene_id},
            env=env,
        )
        text = out.messages[0].text
        # aliases = base ∪ live add; home_place resolves + wraps to an EntryRef.
        self.assertIn("The Salamander", text)
        self.assertIn("Steadholder", text)
        self.assertTrue(text.endswith("|Manticore"))


class EntryAmbientSceneTests(_HelperFixtureBase):
    """ADR-0060 §3: `entry(x)` reads x as of the prompt's *ambient* `scene` — the
    zero-arg "this node as it is here" default — book-start when no scene is set.
    `original(x)` and an explicit `at=None` are always book-start."""

    def _promote_honor_in_scene_two(self) -> None:
        self._update_scene_with_mutations(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                "Honor is promoted. "
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
            ),
        )

    def _render(self, template: str, scene: object) -> str:
        env = create_environment_for_project(self.service)
        out = render_template(
            template, context={"who": self.honor["id"], "scene": scene}, env=env
        )
        return out.messages[0].text.strip()

    def test_entry_defaults_to_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # Ambient scene = scene_two, where the promotion is live → as-of read.
        text = self._render(
            '{% role "system" %}{{ entry(who).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Admiral Harrington")

    def test_entry_book_start_when_no_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        text = self._render(
            '{% role "system" %}{{ entry(who).title }}{% endrole %}', None
        )
        self.assertEqual(text, "Honor Harrington")

    def test_original_ignores_the_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # Even under a scene where the mutation is live, `original()` is book-start.
        text = self._render(
            '{% role "system" %}{{ original(who).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Honor Harrington")

    def test_explicit_at_none_overrides_ambient_scene(self) -> None:
        self._promote_honor_in_scene_two()
        # `at=None` explicitly forces book-start, even under an as-of ambient scene.
        text = self._render(
            '{% role "system" %}{{ entry(who, at=None).title }}{% endrole %}',
            self.scene_two_node.scene_id,
        )
        self.assertEqual(text, "Honor Harrington")

    def test_node_field_sugar_matches_metadata_escape(self) -> None:
        # `node.<field>` resolves the same value as the `node.metadata.<field>`
        # escape (ADR-0060 §3); the escape stays valid.
        text = self._render(
            '{% role "system" %}{{ entry(who).aliases | join(",") }}'
            '|{{ entry(who).metadata.aliases | join(",") }}{% endrole %}',
            None,
        )
        self.assertEqual(text, "The Salamander|The Salamander")


class ImpersonateAsOfPreviewTests(_HelperFixtureBase):
    """The anchor rides the prompt's `as_of` scene input (slider-seeded at launch,
    persisted with the chat's inputs) → `inputs.as_of` → `entry(…, at=as_of)`, so
    an impersonate render reads its subject as-of the anchor scene (ADR-0060 §3).
    Mirrors impersonate.md's two key lines; the render takes no as-of param."""

    IMPERSONATE = (
        '{% set as_of = inputs.as_of if inputs.as_of is defined else "" %}'
        "{% set char = entry(inputs.entry, at=as_of) %}"
        '{% role "system" %}You ARE {{ char.title }}.\n'
        "{% if char.body %}{{ char.body }}{% endif %}{% endrole %}"
    )

    def _mutate(self) -> None:
        from urllib.parse import quote

        new_body = quote("Admiral of the Fleet.")
        self._update_scene_with_mutations(
            self.scene_two_node.scene_id,
            title="The Arrival",
            entry_type="manuscript:scene",
            metadata={"summary": "x", "characters": [], "pov": self.honor["id"]},
            body=(
                f"<!-- mutate:entity={self.honor['id']};field=title;value=Admiral%20Harrington;id=m1 -->"
                f"<!-- mutate:entity={self.honor['id']};field=body;value={new_body};id=m2 -->"
            ),
        )

    def _preview(self, as_of_scene: str) -> str:
        from app.services.ai.preview import PreviewRequest, build_preview

        # The anchor rides the prompt's hidden `as_of` input (launch-seeded),
        # persisted with the chat's inputs — not a build_preview parameter.
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=self.IMPERSONATE,
                target_scene_id="",
                session_id=None,
                inputs={"entry": self.honor["id"], "as_of": as_of_scene},
                text_before="",
                text_after="",
                commit=False,
                subject=self.honor["id"],
            ),
        )
        return "\n".join(m.text for m in rendered.messages)

    def test_render_reads_as_of_anchor(self) -> None:
        self._mutate()
        text = self._preview(self.scene_two_node.scene_id)
        self.assertIn("You ARE Admiral Harrington.", text)
        self.assertIn("Admiral of the Fleet.", text)

    def test_render_without_anchor_is_base(self) -> None:
        self._mutate()
        text = self._preview("")
        self.assertIn("You ARE Honor Harrington.", text)
        self.assertIn("Captain of the Fearless.", text)
