"""Prompt metadata layer overrides (#1738 / ADR-0039).

An inherited prompt — a built-in Library node or an ancestor project's prompt —
is read-only in place: its body and inputs stay fork-only. But its *metadata*
(the routing fields `preferred_assistant_id` / `assistant_tags`, plus `color`)
is editable in place, saved as the consuming layer's sparse override, exactly as
lore already works (`test_layer_overrides.py`). These tests reuse that mechanism
for the prompt kind: the value fold on read, the entity_ref edge fold, the
composite revision, reset-to-inherited, the owned-save split, and the guarantee
that overriding an inherited prompt never rewrites the ancestor's file.

The chain is the four layers the lore suite uses:
`writing (base) -> honorverse (universe) -> honor-harrington (series) -> book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from layer_fixtures import declare_full_chain

from app.models import (
    CreateAssistantEntryRequest,
    CreatePromptEntryRequest,
    CreateTagEntryRequest,
    SaveAssistantEntryRequest,
    SavePromptEntryRequest,
)
from app.services import machine_settings as ms_service
from app.services.project.errors import ProjectServiceError
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project_service import ProjectService


class PromptOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        # Assistant-tags registration on save writes the machine-global vocabulary
        # (#88); point it at a temp config so the test never touches real state.
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_prompt_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        """Write a prompt file directly at a layer, bypassing the create dance."""
        (folder / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "prompts" / f"{node_id}.md",
            node_id,
            title,
            "prompt:general",
            metadata,
            "Prompt body.",
            extra={"inputs": []},
            omit_empty_metadata=True,
        )

    def _make_assistant(self, title: str, *, layer: Path) -> str:
        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(
                title=title, entry_type="assistant:assistant", layer_id=self._layer_id(layer)
            )
        )
        self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(title=title, entry_type="assistant:assistant", metadata={}),
        )
        return entry.id

    def _tag(self, title: str) -> str:
        # ADR-0082 §2: `assistant_tags` is now an `entity_ref_list` of real
        # tag-node ids — the override fold is generic list-add machinery, so
        # these tests exercise it with real ids rather than free-text names
        # (which the validated read path would heal away as dangling).
        return self.service.create_tag_entry(
            CreateTagEntryRequest(title=title, entry_type="tag:assistant_tag")
        ).id

    def _save_override(
        self,
        entry_id: str,
        metadata: dict,
        *,
        layer: Path | None = None,
        clear: list[str] | None = None,
        base_revision: str | None = None,
    ):
        return self.service.save_prompt_entry(
            entry_id,
            SavePromptEntryRequest(
                title="Revise plotline",
                body="Prompt body.",
                entry_type="prompt:general",
                metadata=metadata,
                authoring_layer_id=self._layer_id(layer) if layer is not None else None,
                clear_override_fields=clear or [],
                base_revision=base_revision,
            ),
        )

    # --- the value fold ------------------------------------------------

    def test_override_changes_the_effective_value_and_leaves_the_ancestor_untouched(self) -> None:
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        series_file = self.series / "prompts" / "revise.md"
        before = series_file.read_text(encoding="utf-8")

        self._save_override("revise", {"color": "amber"})

        # The open project sees the override…
        folded = self.service.read_prompt_entry("revise")
        self.assertEqual(folded.metadata["color"], "amber")
        self.assertEqual(folded.overridden_fields, ["color"])
        self.assertFalse(folded.editable)  # the body stays fork-only
        # …the ancestor's file is byte-for-byte unchanged…
        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        # …and the delta lives at the book, not upstream.
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        self.assertFalse((self.series / OVERRIDES_FOLDER).exists())

    def test_assistant_tags_override_adds_and_keeps_later_ancestor_additions(self) -> None:
        beta, romance, gamma = self._tag("Beta"), self._tag("Romance"), self._tag("Gamma")
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"assistant_tags": [beta]})
        # The book adds one tag via an override.
        self._save_override("revise", {"assistant_tags": [beta, romance]})
        self.assertEqual(
            self.service.read_prompt_entry("revise").metadata["assistant_tags"],
            [beta, romance],
        )

        # The series later gains a *different* tag. Because the override is an
        # `add`, not a whole-list replace, the ancestor addition still flows down.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"assistant_tags": [beta, gamma]})
        self.assertEqual(
            self.service.read_prompt_entry("revise").metadata["assistant_tags"],
            [beta, gamma, romance],
        )

    def test_the_prompt_list_shows_the_effective_overridden_value(self) -> None:
        # list_prompt_entries opts into the fold (the display list must show the
        # effective value); the snippet-render path does not. Pins that opt-in.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        self._save_override("revise", {"color": "amber"})
        summary = next(e for e in self.service.list_prompt_entries().entries if e.id == "revise")
        self.assertEqual(summary.metadata["color"], "amber")

    def test_effective_edges_reflect_a_preferred_assistant_override(self) -> None:
        muse = self._make_assistant("Muse", layer=self.root)
        self._write_prompt_at(self.series, "describe", "Describe", {})

        # No preferred assistant yet → the assistant has no backlink from the prompt.
        index = self.service._build_node_index()
        self.assertEqual(index.edges_by_dst.get(muse, []), [])

        # The book points the prompt's preferred assistant via an override.
        self._save_override("describe", {"preferred_assistant_id": muse})

        # The entity_ref survives the read fold (its target exists, so it is not
        # stripped) and it is marked overridden…
        folded = self.service.read_prompt_entry("describe")
        self.assertEqual(folded.metadata["preferred_assistant_id"], muse)
        self.assertEqual(folded.overridden_fields, ["preferred_assistant_id"])
        # …and the index's effective edges reflect the override with no scope
        # parameter — the prompt now backlinks the assistant (the edge fold, which
        # this change extended from lore-only to prompts).
        index = self.service._build_node_index()
        self.assertIn("describe", [edge.src for edge in index.edges_by_dst.get(muse, [])])

    # --- composite revision --------------------------------------------

    def test_revision_changes_when_an_override_in_the_chain_changes(self) -> None:
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        before = self.service.read_prompt_entry("revise").revision
        self._save_override("revise", {"color": "amber"})
        after = self.service.read_prompt_entry("revise").revision
        self.assertNotEqual(before, after)

    def test_revision_is_unchanged_for_a_prompt_with_no_overrides(self) -> None:
        # The composite over a single file reproduces the plain per-file revision.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        entry = self.service.read_prompt_entry("revise")
        series_file = self.series / "prompts" / "revise.md"
        self.assertEqual(entry.revision, self.service._revision(series_file))

    def test_a_stale_base_revision_is_rejected(self) -> None:
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        opened = self.service.read_prompt_entry("revise")
        # Someone else lands an override first, moving the composite revision on.
        self._save_override("revise", {"color": "amber"})
        with self.assertRaises(ProjectServiceError) as caught:
            self._save_override("revise", {"color": "moss"}, base_revision=opened.revision)
        self.assertEqual(caught.exception.status_code, 409)

    # --- the write safety ----------------------------------------------

    def test_saving_an_inherited_prompt_writes_an_override_never_the_ancestor(self) -> None:
        # Unlike lore (which refuses a no-target save), a prompt override defaults
        # to the open project — there is no data-loss risk because it never
        # rewrites the ancestor's canon, it only lays a delta below it.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        series_file = self.series / "prompts" / "revise.md"
        before = series_file.read_text(encoding="utf-8")

        self._save_override("revise", {"color": "amber"})  # no explicit layer

        self.assertEqual(series_file.read_text(encoding="utf-8"), before)
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

    def test_a_body_change_to_an_inherited_prompt_is_refused_and_writes_nothing(self) -> None:
        # The body stays read-only in place. A save that changes the body is refused
        # (409) BEFORE any override is written — even when metadata also changed, so
        # the refusal is atomic and the effective value is untouched.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_prompt_entry(
                "revise",
                SavePromptEntryRequest(
                    title="Revise plotline",
                    body="hijacked body",
                    entry_type="prompt:general",
                    metadata={"color": "amber"},
                    authoring_layer_id=self._layer_id(self.root),
                ),
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())
        self.assertEqual(self.service.read_prompt_entry("revise").metadata["color"], "slate")

    def test_authoring_at_or_above_the_owning_layer_is_refused(self) -> None:
        # The prompt is owned by the series; an override must sit strictly below it.
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        with self.assertRaises(ProjectServiceError) as caught:
            self._save_override("revise", {"color": "amber"}, layer=self.series)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())

    def test_a_book_local_prompt_still_saves_in_place(self) -> None:
        # A prompt the book owns is not inherited, so a plain save writes its own
        # file — no override, and nothing marked overridden.
        created = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Local Prompt", entry_type="prompt:general")
        )
        saved = self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Local Prompt", body="Body.", entry_type="prompt:general", metadata={"color": "moss"}
            ),
        )
        self.assertEqual(saved.metadata["color"], "moss")
        self.assertEqual(saved.overridden_fields, [])
        self.assertTrue(saved.editable)
        self.assertFalse((self.root / OVERRIDES_FOLDER).exists())

    # --- reset-to-inherited --------------------------------------------

    def test_reverting_an_override_to_canon_drops_the_delta_file(self) -> None:
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"color": "slate"})
        self._save_override("revise", {"color": "amber"})
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        # Saving the canon value back produces an empty delta → the file is dropped.
        self._save_override("revise", {"color": "slate"})
        self.assertFalse(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        self.assertEqual(self.service.read_prompt_entry("revise").metadata["color"], "slate")

    def test_clearing_a_field_reverts_it_while_other_overrides_stay(self) -> None:
        beta, romance = self._tag("Beta"), self._tag("Romance")
        self._write_prompt_at(
            self.series, "revise", "Revise plotline", {"color": "slate", "assistant_tags": [beta]}
        )
        # Override two fields at the book.
        self._save_override("revise", {"color": "amber", "assistant_tags": [beta, romance]})
        self.assertEqual(sorted(self.service.read_prompt_entry("revise").overridden_fields), ["assistant_tags", "color"])

        # Clear just `color`. Its submitted value is still the override "amber", but
        # the clear signal drops the row regardless → it reverts to the ancestor's
        # "slate"; the assistant_tags override is untouched.
        cleared = self._save_override(
            "revise",
            {"color": "amber", "assistant_tags": [beta, romance]},
            layer=self.root,
            clear=["color"],
        )
        self.assertEqual(cleared.metadata["color"], "slate")
        self.assertEqual(cleared.metadata["assistant_tags"], [beta, romance])
        self.assertEqual(cleared.overridden_fields, ["assistant_tags"])
        text = next((self.root / OVERRIDES_FOLDER).glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("assistant_tags", text)
        self.assertNotIn("color", text)

    # --- vocabulary registration ---------------------------------------

    def test_effective_assistant_tags_are_not_registered_in_the_legacy_vocabulary(self) -> None:
        # ADR-0082 §2: `assistant_tags` holds tag-node ids now, not free-text
        # names — registering an id into the legacy name-keyed
        # `assistant-tags.yaml` would corrupt it, so an override save (like an
        # owned save, test_tag_bindings.py) no longer registers at all (#88's
        # registration retired here; the store itself is dead code until a
        # later slice removes it).
        romance = self._tag("Romance")
        before = ms_service.load_assistant_tags()
        self._write_prompt_at(self.series, "revise", "Revise plotline", {"assistant_tags": []})
        self._save_override("revise", {"assistant_tags": [romance]})
        self.assertEqual(ms_service.load_assistant_tags(), before)


if __name__ == "__main__":
    unittest.main()
