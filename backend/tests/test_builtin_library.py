"""ADR-0049 slice 1: the built-in Library resolves as a read-only ancestor
layer of shipped prompt nodes.

The Library is an app-owned floor beneath every project — the node analogue of
`default_schema.py` at the base of the schema merge. A fresh project sees the
shipped prompts (so `/roleplay` runs out of the box) without a single file
landing in its folders, and they are read-only in place: the only way to change
one is to clone it. These tests pin resolve / no-clutter / read-only, the
`is_library` read-model flag, and the clone gesture (§5) — plus that the shipped
bodies carry their wiring, now that they live only in the Library and no longer
shadow a type `default_body` (§7).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.models import SavePromptEntryRequest
from app.services.project import node_index_snapshot as snapshot
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService

LIBRARY_IDS = {"builtin-roleplay", "builtin-revise-entry"}


class BuiltinLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Library Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _summaries(self) -> dict[str, object]:
        return {e.id: e for e in self.service.list_prompt_entries().entries}

    def test_library_prompts_resolve_in_a_fresh_project(self) -> None:
        entries = self._summaries()
        for lib_id in LIBRARY_IDS:
            self.assertIn(lib_id, entries, f"{lib_id} should resolve out of the box")
            self.assertEqual(entries[lib_id].source_layer_label, "Library")
            # The read-model flag the frontend branches clone/hide on (#674) —
            # not the display label, which a writer's own project could reuse.
            self.assertTrue(entries[lib_id].is_library)
        # And they read as inherited, not owned by the open project.
        own_layer_id = self.service._metadata_schema_layer_id(self.root)
        for lib_id in LIBRARY_IDS:
            self.assertNotEqual(entries[lib_id].source_layer_id, own_layer_id)

    def test_library_does_not_clutter_the_project_folder(self) -> None:
        """The core anti-requirement: shipped material is present but no file is
        written into the writer's folders."""
        # The prompts folder exists (scaffolded) but is empty of shipped files.
        self.assertEqual(list((self.root / "prompts").glob("*.md")), [])
        # Yet the shipped prompts resolve, and one reads back by id (runnable).
        self.assertTrue(set(self._summaries()) >= LIBRARY_IDS)
        roleplay = self.service.read_prompt_entry("builtin-roleplay")
        self.assertIn("character_thread", roleplay.body)

    def test_library_prompt_cannot_be_saved_in_place(self) -> None:
        before = self._library_path("builtin-roleplay").read_bytes()
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_prompt_entry(
                "builtin-roleplay",
                SavePromptEntryRequest(
                    title="Roleplay",
                    body="hijacked",
                    base_revision="",
                    entry_type="prompt:roleplay",
                    metadata={},
                ),
            )
        self.assertEqual(ctx.exception.status_code, 409)
        # The bundled app file is untouched — read-only by construction.
        self.assertEqual(self._library_path("builtin-roleplay").read_bytes(), before)

    def test_library_prompt_cannot_be_deleted(self) -> None:
        before = self._library_path("builtin-revise-entry").read_bytes()
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_prompt_entry("builtin-revise-entry")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._library_path("builtin-revise-entry").read_bytes(), before)
        # Still listed after the refused delete.
        self.assertIn("builtin-revise-entry", self._summaries())

    def test_owned_prompt_coexists_with_the_library(self) -> None:
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Mine", "entry_type": "prompt:general"})()
        )
        entries = self._summaries()
        self.assertIn(created.id, entries)
        self.assertTrue(set(entries) >= LIBRARY_IDS)
        # The owned prompt is editable in place (the guard only bites inherited).
        own = self.service.read_prompt_entry(created.id)
        self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Mine",
                body="my body",
                base_revision=own.revision,
                entry_type="prompt:general",
                metadata={},
            ),
        )

    def test_editable_flag_mirrors_the_read_only_guard(self) -> None:
        """The `editable` read-model flag is the frontend's single source for the
        read-only lock (#689), so it must equal exactly what `save_prompt_entry`
        enforces — proven here by pairing each flag value with the write it
        promises. If the flag ever drifts from the 409, this fails.
        """
        summaries = self._summaries()
        for lib_id in LIBRARY_IDS:
            # Inherited Library prompts read as NOT editable on BOTH read models.
            self.assertFalse(summaries[lib_id].editable, f"{lib_id} is inherited")
            self.assertFalse(self.service.read_prompt_entry(lib_id).editable)
        # editable=False is not decorative: the save it forbids really 409s.
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_prompt_entry(
                "builtin-roleplay",
                SavePromptEntryRequest(
                    title="Roleplay",
                    body="hijacked",
                    base_revision="",
                    entry_type="prompt:roleplay",
                    metadata={},
                ),
            )
        self.assertEqual(ctx.exception.status_code, 409)
        # The read-only guard covers DELETE too (delete_prompt_entry runs the same
        # reject), so editable=False must mirror that as well, not just save.
        with self.assertRaises(ProjectServiceError) as del_ctx:
            self.service.delete_prompt_entry("builtin-revise-entry")
        self.assertEqual(del_ctx.exception.status_code, 409)
        # An owned prompt reads editable=True on both read models, and the save
        # that value promises actually succeeds.
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Mine", "entry_type": "prompt:general"})()
        )
        self.assertTrue(self.service.read_prompt_entry(created.id).editable)
        self.assertTrue(self._summaries()[created.id].editable)
        own = self.service.read_prompt_entry(created.id)
        self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Mine",
                body="my body",
                base_revision=own.revision,
                entry_type="prompt:general",
                metadata={},
            ),
        )

    def test_shipped_bodies_carry_their_wiring(self) -> None:
        """The shipped bodies live only in the Library now (§7 retired their type
        `default_body`), so the coverage that they wire the right helpers moves
        here, onto the resolved Library node body.

        Roleplay must still read the #317 project-metadata triple out of the box;
        revise:entry must still carry both of its modes (revise via
        `field_catalog(e)`, create via `field_catalog(draft_type)` /
        `entry_type_label(draft_type)`). Since ADR-0051 S4 the seed no longer
        carries the JSON commit contract — it is a goal-directed brainstorm and
        the structured result is extracted separately at commit.
        """
        roleplay = self.service.read_prompt_entry("builtin-roleplay").body
        for marker in (
            "project.metadata.tense",
            "project.metadata.measurement_system",
            "project.metadata.spelling",
            "character_thread",
        ):
            self.assertIn(marker, roleplay)
        revise = self.service.read_prompt_entry("builtin-revise-entry").body
        for marker in (
            "ideation partner",
            "entry(input.entry)",
            "field_catalog(e)",
            "field_catalog(draft_type)",
            "entry_type_label(draft_type)",
            "ready to commit",
        ):
            self.assertIn(marker, revise)
        # The JSON format contract moved to the extraction endpoint (S4) — the
        # seed must NOT emit it, or the model would dump JSON mid-conversation.
        self.assertNotIn('"fields"', revise)

    def test_project_settings_snippet_resolves_and_wires_in(self) -> None:
        """#1020 / finishes #317: a built-in `prompt:snippet` surfaces the
        project's authored settings, and revise:entry pulls it in so a brainstorm
        knows the project's language/units/spelling out of the box."""
        entries = self._summaries()
        self.assertIn("builtin-project-settings", entries)
        self.assertTrue(entries["builtin-project-settings"].is_library)
        body = self.service.read_prompt_entry("builtin-project-settings").body
        # Reads labels from the project type and skips the `color` field.
        self.assertIn('field_catalog("project:project")', body)
        self.assertIn('f.id != "color"', body)
        revise = self.service.read_prompt_entry("builtin-revise-entry").body
        self.assertIn('{% include "builtin-project-settings" %}', revise)

    def test_project_settings_snippet_renders_the_authored_settings(self) -> None:
        """The snippet lists the project's set fields (renders clean, with the
        `## Project settings` heading) and omits unset ones."""
        from app.models import SaveProjectNodeRequest
        from app.services.ai.helpers import create_environment_for_project
        from app.services.ai.templates import render_template

        current = self.service.read_project_node()
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title=current.title,
                body="",
                entry_type=current.entry_type,
                metadata={"author": "Jane Roe", "measurement_system": "metric"},
            )
        )
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "system" %}{% include "builtin-project-settings" %}{% endrole %}',
            context={"project": self.service.current_project()},
            env=env,
        )
        text = out.messages[0].text
        self.assertIn("## Project settings", text)
        self.assertIn("Jane Roe", text)
        self.assertIn("metric", text)

    def test_project_settings_snippet_is_inert_without_a_project(self) -> None:
        """Rendered in a context that does not define `project` (e.g. the unit
        tests that render revise:entry with only `input`), the snippet must be
        inert — it guards with `project is defined`, so a StrictUndefined
        boolean check never raises."""
        from app.services.ai.helpers import create_environment_for_project

        env = create_environment_for_project(self.service)
        out = env.from_string(
            '{% role "system" %}before{% include "builtin-project-settings" %}after{% endrole %}'
        ).render()
        self.assertNotIn("## Project settings", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_clone_a_library_prompt_into_the_project(self) -> None:
        """Clone (§5): a shipped prompt is lifted into the project under a NEW id
        as an editable copy. The Library original is untouched and still resolves
        — clone is not hide."""
        before = self._library_path("builtin-roleplay").read_bytes()
        source = self.service.read_prompt_entry("builtin-roleplay")
        clone = self.service.fork_prompt_entry("builtin-roleplay")
        # New id, owned by the project (not the Library floor), and not shipped.
        self.assertNotEqual(clone.id, "builtin-roleplay")
        self.assertFalse(clone.is_library)
        # The whole point of the clone: it is now editable in place (#689).
        self.assertTrue(clone.editable)
        self.assertEqual(clone.source_layer_id, self.service._metadata_schema_layer_id(self.root))
        # A faithful copy: title, body and inputs carried from the shipped node.
        self.assertEqual(clone.title, source.title)
        self.assertEqual(clone.body.rstrip(), source.body.rstrip())
        self.assertEqual(
            [i.model_dump(exclude_none=True) for i in clone.inputs],
            [i.model_dump(exclude_none=True) for i in source.inputs],
        )
        # The copy lands as a real project file; the shipped original is byte-for-
        # byte untouched and still resolves.
        self.assertEqual(len(list((self.root / "prompts").glob("*.md"))), 1)
        self.assertEqual(self._library_path("builtin-roleplay").read_bytes(), before)
        self.assertIn("builtin-roleplay", self._summaries())
        # And the owned copy is now saveable in place (the read-only guard is off).
        saved = self.service.save_prompt_entry(
            clone.id,
            SavePromptEntryRequest(
                title=clone.title,
                body="edited",
                base_revision=clone.revision,
                entry_type=clone.entry_type,
                metadata={},
            ),
        )
        self.assertEqual(saved.body.rstrip(), "edited")

    def test_cannot_clone_a_prompt_the_project_owns(self) -> None:
        """Clone is for shipped material; an already-owned prompt has nothing to
        lift."""
        created = self.service.create_prompt_entry(
            type("R", (), {"title": "Mine", "entry_type": "prompt:general"})()
        )
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.fork_prompt_entry(created.id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_cannot_clone_a_missing_prompt(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.fork_prompt_entry("no-such-prompt")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_library_survives_a_snapshot_reload(self) -> None:
        """The node index persists to a snapshot that a *second* open reads
        instead of rebuilding. The Library must round-trip through it, or the
        shipped prompts would resolve on the first open and silently vanish on
        the next."""
        # First build persists the snapshot; it must carry the Library entries.
        self.service._build_node_index(self.root)
        snapshot_text = snapshot.snapshot_path(self.root).read_text(encoding="utf-8")
        for lib_id in LIBRARY_IDS:
            self.assertIn(lib_id, snapshot_text)
        # Drop the in-memory memo so the next build reloads from that snapshot —
        # what a fresh open does — and the Library must still resolve, labelled.
        node_index_gate.invalidate()
        entries = self._summaries()
        self.assertTrue(set(entries) >= LIBRARY_IDS)
        for lib_id in LIBRARY_IDS:
            self.assertEqual(entries[lib_id].source_layer_label, "Library")
            # `is_library` is re-stamped from the layer on rehydrate, NOT read
            # from the serialized entry. If the warm load drops it, the pill
            # (which reads the label) still renders but clone/read-only break
            # (#674) — so assert the flag, not just the label.
            self.assertTrue(entries[lib_id].is_library)
            # `editable` is a SEPARATE axis from is_library: it derives from the
            # restored `source_layer_id`, not the re-stamped is_library flag. A
            # warm load that mis-restored the source layer would flip an inherited
            # prompt to editable=True on the next open (unlocking a read-only
            # prompt) with is_library still correct — so pin editable too (#689).
            self.assertFalse(entries[lib_id].editable)
            self.assertFalse(self.service.read_prompt_entry(lib_id).editable)
        # The behaviour the flag gates: clone must still work after a warm load,
        # not just resolve. With is_library lost, fork_prompt_entry would 409.
        node_index_gate.invalidate()
        clone = self.service.fork_prompt_entry("builtin-roleplay")
        self.assertFalse(clone.is_library)

    def _library_path(self, entry_id: str) -> Path:
        return self.service._build_node_index().by_id[entry_id].path


class InheritedAncestorPromptCloneTests(unittest.TestCase):
    """#676: an ancestor *project's* prompt is inherited and read-only in place,
    and clones into the open project exactly as a Library prompt does — a new id,
    a faithful copy, the ancestor untouched. The escape hatch is clone, not lore's
    in-place fork-to-here: a prompt is a tool you adapt, not canon you correct."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "universe"
        self.root = self.universe / "book"
        self.service = ProjectService.created_at(self.root, "Book")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # AFTER the patch — declare writes the machine root through config_path().
        declare_full_chain(self.service, self.root, self.base)
        # The universe layer defines a CUSTOM prompt sub-type and authors a prompt
        # of it, with an input. So the clone must validate an entry_type that
        # reaches the open project purely through the ancestor schema-layer merge
        # (#676 review) — not a built-in every project already has — and must
        # carry the inputs across.
        self.service._write_yaml(
            self.universe / "metadata.schema.yaml",
            {
                "entry_types": {
                    "prompt:worldbuilding": {
                        "name": "Worldbuilding",
                        "kind": "prompt",
                        "parent": "prompt:general",
                    },
                },
            },
        )
        (self.universe / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.universe / "prompts" / "universe-prompt.md",
            "universe-prompt",
            "Universe Prompt",
            "prompt:worldbuilding",
            {},
            "ancestor body {{ scene }}",
            extra={"inputs": [{"name": "topic", "type": "text", "label": "Topic", "required": False}]},
        )
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _own_layer(self) -> str:
        return self.service._metadata_schema_layer_id(self.root)

    def test_ancestor_prompt_resolves_as_inherited(self) -> None:
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertIn("universe-prompt", entries)
        # Inherited (source layer != own) and NOT shipped Library material.
        self.assertNotEqual(entries["universe-prompt"].source_layer_id, self._own_layer())
        self.assertFalse(entries["universe-prompt"].is_library)
        # An inherited ancestor prompt (not just Library) reads read-only via the
        # editable flag on both read models — the lock the frontend keys on (#689).
        self.assertFalse(entries["universe-prompt"].editable)
        self.assertFalse(self.service.read_prompt_entry("universe-prompt").editable)

    def test_ancestor_prompt_is_read_only_in_place(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.save_prompt_entry(
                "universe-prompt",
                SavePromptEntryRequest(
                    title="Universe Prompt",
                    body="hijacked",
                    base_revision="",
                    entry_type="prompt:worldbuilding",
                    metadata={},
                ),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_ancestor_prompt_delete_is_refused(self) -> None:
        # The generalized read-only guard (#676) refuses DELETE of an inherited
        # ancestor prompt too, not just save — the delete half was only covered
        # for the Library. editable=False must mirror this refusal.
        self.assertFalse(self.service.read_prompt_entry("universe-prompt").editable)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_prompt_entry("universe-prompt")
        self.assertEqual(ctx.exception.status_code, 409)
        # Still resolves after the refused delete (unchanged, not gone).
        entries = {e.id: e for e in self.service.list_prompt_entries().entries}
        self.assertIn("universe-prompt", entries)

    def test_clone_an_ancestor_prompt_into_the_project(self) -> None:
        source = self.service.read_prompt_entry("universe-prompt")
        clone = self.service.fork_prompt_entry("universe-prompt")
        # New id, owned by the open project, not shipped.
        self.assertNotEqual(clone.id, "universe-prompt")
        self.assertFalse(clone.is_library)
        self.assertTrue(clone.editable)
        self.assertEqual(clone.source_layer_id, self._own_layer())
        # Faithful copy; the ancestor original still resolves (clone, not move).
        self.assertEqual(clone.title, source.title)
        self.assertEqual(clone.body.rstrip(), source.body.rstrip())
        # The custom, ancestor-DEFINED entry_type survives the merge-validated
        # create+save (the seam #676 relies on), and the inputs carry across.
        self.assertEqual(clone.entry_type, source.entry_type)
        self.assertEqual(clone.entry_type, "prompt:worldbuilding")
        self.assertEqual(
            [i.model_dump(exclude_none=True) for i in clone.inputs],
            [i.model_dump(exclude_none=True) for i in source.inputs],
        )
        self.assertEqual(len(list((self.root / "prompts").glob("*.md"))), 1)
        self.assertIn(
            "universe-prompt",
            {e.id for e in self.service.list_prompt_entries().entries},
        )
        # The copy is saveable in place — the inherited read-only guard is off.
        saved = self.service.save_prompt_entry(
            clone.id,
            SavePromptEntryRequest(
                title=clone.title,
                body="edited",
                base_revision=clone.revision,
                entry_type=clone.entry_type,
                metadata={},
            ),
        )
        self.assertEqual(saved.body.rstrip(), "edited")


if __name__ == "__main__":
    unittest.main()
