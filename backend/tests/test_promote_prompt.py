"""Promoting a prompt to an ancestor project (#1663 / ADR-0078 slice 3).

Builds on slice 2's core (`test_promote_lore.py`). New here: the §5 dynamic-
reference list (a `context_pick` input travels and re-resolves untouched), and
§6's include-closure cascade — a prompt's `{% include %}`d snippets are its
one hard dependency and must be promoted with it, refusing (★) when the
closure itself is unknowable because of a dynamically-named include.

Same fixture chain as `test_promote_lore.py`:
`writing (base) -> honorverse (universe) -> honor-harrington (series) -> book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _builtins import builtin_prompt_id
from layer_fixtures import declare_full_chain

from app.services.project.errors import ProjectServiceError
from app.services.project.references import INCLUDE_FIELD_ID
from app.services.project_service import ProjectService


class PromotePromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)
        self.series_layer_id = self.service._metadata_schema_layer_id(self.series)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    # --- fixture helpers -------------------------------------------------

    def _write_ancestor_prompt(
        self,
        folder: Path,
        node_id: str,
        title: str,
        body: str = "",
        entry_type: str = "prompt:general",
        inputs: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> None:
        (folder / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "prompts" / f"{node_id}.md",
            node_id,
            title,
            entry_type,
            metadata or {},
            body,
            extra={"inputs": inputs or []},
            omit_empty_metadata=True,
        )

    def _find_prompt_path(self, folder: Path, node_id: str) -> Path:
        """Locate a prompt by front-matter id under `folder/prompts/` — the
        promoted file is named from the TITLE (`_filepath_for_new_node`), not
        `{id}.md` (the POSIX trap that bit slice 2, `test_promote_lore.py`)."""
        for path in sorted((folder / "prompts").glob("*.md")):
            front_matter = self.service._read_front_matter_only(path, strict=True)
            if (front_matter.get("id") or path.stem) == node_id:
                return path
        raise AssertionError(f"No prompt node {node_id!r} on disk under {folder}")

    def _snapshot_files(self, folder: Path) -> set[str]:
        return {
            str(p.relative_to(folder))
            for p in folder.rglob("*")
            if p.is_file() and ".cache" not in p.relative_to(folder).parts
        }

    def _define_group_list_field_at(
        self, folder: Path, field_id: str, member_key: str, *, entry_type: str
    ) -> None:
        """Author a `list`-of-`item_group` field at `folder` whose named group has
        one `entity_ref` member — the ADR-0081 §4 shape, `item_members` derived
        from the group by the resolver."""
        path = folder / "metadata.schema.yaml"
        data = self.service._read_yaml(path)
        data.setdefault("groups", {})[f"{field_id}_grp"] = {
            "name": field_id.capitalize(),
            "members": [{"key": member_key, "name": member_key.capitalize(), "type": "entity_ref"}],
        }
        data.setdefault("fields", {})[field_id] = {
            "name": field_id.capitalize(),
            "type": "list",
            "item_group": f"{field_id}_grp",
        }
        entry = data.setdefault("entry_types", {}).get(entry_type) or {}
        own = list(entry.get("fields") or [])
        if field_id not in own:
            own.insert(0, field_id)
        entry["fields"] = own
        data["entry_types"][entry_type] = entry
        self.service._write_yaml(path, data)

    # --- 1: moves the file, keeps the id; refusals ------------------------

    def test_promote_prompt_moves_file_keeps_id(self) -> None:
        self._write_ancestor_prompt(self.root, "genprompt", "General Prompt", body="Hello.")

        promoted = self.service.promote_prompt_entry("genprompt", self.series_layer_id)

        self.assertEqual(promoted.id, "genprompt")
        self.assertEqual(promoted.source_layer_id, self.series_layer_id)
        self._find_prompt_path(self.series, "genprompt")  # raises if absent
        self.assertEqual(list((self.root / "prompts").glob("*.md")), [])

    def test_promote_prompt_refuses_inherited(self) -> None:
        self._write_ancestor_prompt(self.universe, "genprompt", "General Prompt")

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_prompt_entry("genprompt", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_promote_prompt_refuses_non_ancestor_target(self) -> None:
        self._write_ancestor_prompt(self.root, "genprompt", "General Prompt")
        book01_layer_id = self.service._metadata_schema_layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_prompt_entry("genprompt", book01_layer_id)
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ProjectServiceError) as ctx2:
            self.service.promote_prompt_entry("genprompt", "not-a-real-layer")
        self.assertEqual(ctx2.exception.status_code, 400)

    # --- 1a (ADR-0081 §4): a prompt's nested origin-local ref blocks too -----

    def test_prompt_nested_origin_local_ref_blocks_promotion(self) -> None:
        # A prompt's metadata carries refs like any node; a nested one pointing at
        # an origin-local target refuses the promotion (same channel as a lore
        # node — the shared `_partition_node_metadata` block, wired into the prompt
        # plan alongside the §6 include refusal).
        self._define_group_list_field_at(self.universe, "bonds", "who", entry_type="prompt:general")
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.root / "lore" / "rustyanchor.md", "rustyanchor", "The Rusty Anchor", "lore:note", {}, ""
        )
        self._write_ancestor_prompt(
            self.root, "genprompt", "General Prompt", body="Hi.", metadata={"bonds": [{"who": "rustyanchor"}]}
        )

        plan = self.service.preview_prompt_promotion("genprompt", self.series_layer_id)
        self.assertIsNotNone(plan.blocked_reason)
        self.assertIn("The Rusty Anchor", plan.blocked_reason)

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_prompt_entry("genprompt", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(list((self.series / "prompts").glob("*.md")), [])

    # --- 2: include closure cascades ---------------------------------------

    def test_include_closure_cascades(self) -> None:
        self._write_ancestor_prompt(
            self.root, "snip", "Snip", body="Some reusable voice guidance.", entry_type="prompt:snippet"
        )
        self._write_ancestor_prompt(self.root, "prompta", "Prompt A", body='{% include "snip" %}\n')

        # The include edge resolves before promotion — verify the fixture is
        # sound before trusting the cascade against it.
        index = self.service._build_node_index()
        self.assertTrue(
            any(
                edge.dst == "snip" and edge.field_id == INCLUDE_FIELD_ID
                for edge in index.edges_by_src.get("prompta", [])
            )
        )

        plan = self.service.preview_prompt_promotion("prompta", self.series_layer_id)
        self.assertEqual(plan.also_promoted, ["Snip"])
        self.assertIsNone(plan.blocked_reason)

        self.service.promote_prompt_entry("prompta", self.series_layer_id)

        self._find_prompt_path(self.series, "prompta")
        self._find_prompt_path(self.series, "snip")
        self.assertEqual(list((self.root / "prompts").glob("*.md")), [])

        series_index = self.service._build_node_index(self.series)
        self.assertEqual(series_index.by_id["prompta"].source_layer_id, self.series_layer_id)
        self.assertEqual(series_index.by_id["snip"].source_layer_id, self.series_layer_id)

    # --- 2a: an included built-in Library snippet is not a blocker (#1674) ----

    def test_include_of_builtin_library_snippet_not_blocked(self) -> None:
        # A prompt that includes an app-shipped Library snippet must promote:
        # the Library is the universal floor (visible from every destination),
        # not an unpromotable intermediate ancestor. Regression for the raw-
        # layer-id block ("... is owned by <id> and can't be lifted from here").
        self._write_ancestor_prompt(
            self.root, "narration", "Narration conventions", body='{% include "Project settings" %}\n'
        )

        # Fixture soundness: the Library include resolves to a real edge.
        index = self.service._build_node_index()
        project_settings_id = builtin_prompt_id(self.service, "Project settings")
        self.assertTrue(
            any(
                edge.dst == project_settings_id and edge.field_id == INCLUDE_FIELD_ID
                for edge in index.edges_by_src.get("narration", [])
            )
        )

        plan = self.service.preview_prompt_promotion("narration", self.series_layer_id)
        self.assertIsNone(plan.blocked_reason)
        # The Library snippet is already visible everywhere — nothing cascades.
        self.assertEqual(plan.also_promoted, [])

        self.service.promote_prompt_entry("narration", self.series_layer_id)
        self._find_prompt_path(self.series, "narration")

    # --- 2b: a closure member owned by an intermediate ancestor blocks -------

    def test_cascade_member_owned_by_intermediate_ancestor_is_blocked(self) -> None:
        universe_layer_id = self.service._metadata_schema_layer_id(self.universe)
        # Two included snippets: `asnip` owned in book01 (promotable, classified
        # FIRST since closure is id-sorted), `zseriessnip` owned at the SERIES —
        # between book01 (origin) and the universe destination, so unpromotable.
        self._write_ancestor_prompt(self.root, "asnip", "A Snip", body="a", entry_type="prompt:snippet")
        self._write_ancestor_prompt(
            self.series, "zseriessnip", "Z Series Snip", body="z", entry_type="prompt:snippet"
        )
        self._write_ancestor_prompt(
            self.root, "bookp", "Book Prompt", body='{% include "asnip" %}{% include "zseriessnip" %}\n'
        )

        # Promote the book prompt UP PAST series, to the universe: the series
        # snippet is not visible there and can't be lifted from book01's scope.
        plan = self.service.preview_prompt_promotion("bookp", universe_layer_id)
        self.assertIsNotNone(plan.blocked_reason)
        assert plan.blocked_reason is not None
        self.assertIn("Z Series Snip", plan.blocked_reason)
        # A blocked plan advertises no cascade, even though `asnip` was
        # classified promotable before the loop hit the member that blocks.
        self.assertEqual(plan.also_promoted, [])

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_prompt_entry("bookp", universe_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)
        # Nothing moved.
        self._find_prompt_path(self.root, "bookp")

    # --- 3 (★): dynamic include is refused ----------------------------------

    def test_dynamic_include_is_refused(self) -> None:
        self._write_ancestor_prompt(
            self.root,
            "dynp",
            "Dynamic Prompt",
            body="{% include input.x %}\n",
            inputs=[{"name": "x", "type": "text"}],
        )

        plan = self.service.preview_prompt_promotion("dynp", self.series_layer_id)
        self.assertIsNotNone(plan.blocked_reason)
        assert plan.blocked_reason is not None
        self.assertIn("dynamic", plan.blocked_reason.lower())

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.promote_prompt_entry("dynp", self.series_layer_id)
        self.assertEqual(ctx.exception.status_code, 422)

        # Nothing moved.
        self._find_prompt_path(self.root, "dynp")
        self.assertEqual(list((self.series / "prompts").glob("*.md")), [])

    # --- 4: context_pick input travels and is listed ------------------------

    def test_context_pick_input_listed(self) -> None:
        self._write_ancestor_prompt(
            self.root,
            "picky",
            "Picky Prompt",
            body="Write about {{ input.topic }}.",
            inputs=[{"name": "topic", "type": "context_pick"}],
        )

        plan = self.service.preview_prompt_promotion("picky", self.series_layer_id)
        self.assertEqual(plan.resolves_differently, ["topic"])

        self.service.promote_prompt_entry("picky", self.series_layer_id)

        series_index = self.service._build_node_index(self.series)
        self.assertEqual(series_index.by_id["picky"].source_layer_id, self.series_layer_id)

    # --- 5: preview is a pure dry-run --------------------------------------

    def test_preview_is_pure_dry_run(self) -> None:
        self._write_ancestor_prompt(
            self.root, "snip", "Snip", body="Some reusable voice guidance.", entry_type="prompt:snippet"
        )
        self._write_ancestor_prompt(self.root, "prompta", "Prompt A", body='{% include "snip" %}\n')
        before_root = self._snapshot_files(self.root)
        before_series = self._snapshot_files(self.series)

        plan = self.service.preview_prompt_promotion("prompta", self.series_layer_id)

        self.assertEqual(plan.destination.layer_id, self.series_layer_id)
        self.assertEqual(plan.also_promoted, ["Snip"])
        self.assertIsNone(plan.blocked_reason)

        self.assertEqual(self._snapshot_files(self.root), before_root)
        self.assertEqual(self._snapshot_files(self.series), before_series)

    # --- 6: lore promotion unchanged by the generalisation ------------------

    def test_lore_promotion_unchanged(self) -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.root / "lore" / "alice.md", "alice", "Alice", "lore:character", {}, ""
        )

        plan = self.service.preview_lore_promotion("alice", self.series_layer_id)

        self.assertEqual(plan.also_promoted, [])
        self.assertEqual(plan.resolves_differently, [])
        self.assertIsNone(plan.blocked_reason)


if __name__ == "__main__":
    unittest.main()
