"""Tests for `POST /api/search/replace` (ADR-0085 §4, slice 3).

Fixtures mirror `test_search_corpus.py`'s `SearchCorpusTestCase` (a fresh
single-layer project) and `OverrideRevisionRefreshTests`/`InheritedLoreTests`
(the universe > series > book chain) for the inherited case.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateCardRequest,
    CreateCharacterArcRequest,
    CreatePlotlineRequest,
    CreatePlotTemplateRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    CreateStructureNodeRequest,
    CreateTagEntryRequest,
    PromptInputDefinition,
    ReplaceHitRef,
    ReplaceRequest,
    SaveCardRequest,
    SaveCharacterArcRequest,
    SaveLoreEntryRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    SaveProjectNodeRequest,
    SavePromptEntryRequest,
    SaveResearchNoteRequest,
    SaveSceneRequest,
    SearchHit,
    SearchRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project_service import ProjectService


def _hit_ref(hit: SearchHit) -> ReplaceHitRef:
    return ReplaceHitRef(
        file_id=hit.file_id,
        field=hit.field,
        start=hit.start,
        end=hit.end,
        text=hit.text,
        revision=hit.revision,
    )


class SearchReplaceTestCase(unittest.TestCase):
    """Base fixture: a fresh single-layer project (copied from
    `test_search_corpus.SearchCorpusTestCase`)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Test Project")
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title=title, body=body, base_revision=scene.revision),
        )
        return scene.id

    def _search(self, query: str) -> list[SearchHit]:
        return self.service.search(SearchRequest(query=query)).hits

    def _body_hits(self, query: str, file_id: str | None = None) -> list[SearchHit]:
        hits = [h for h in self._search(query) if h.field == "body"]
        if file_id is not None:
            hits = [h for h in hits if h.file_id == file_id]
        return hits


class ReplaceOneHitTests(SearchReplaceTestCase):
    def test_replace_first_hit_in_scene(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        before = self.service.read_scene(scene_id)
        hits = sorted(self._body_hits("aetheria", scene_id), key=lambda h: h.start)
        self.assertEqual(len(hits), 2, hits)
        first = hits[0]

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(first)]))

        self.assertEqual(len(response.outcomes), 1)
        outcome = response.outcomes[0]
        self.assertEqual(outcome.status, "replaced")
        self.assertIsNotNone(outcome.revision)
        self.assertNotEqual(outcome.revision, before.revision)
        self.assertEqual(response.replaced_nodes, 1)

        after = self.service.read_scene(scene_id)
        self.assertEqual(after.body, "Aetherion rose. Aetheria fell.\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.status, before.status)
        self.assertEqual(after.entry_type, before.entry_type)
        self.assertEqual(after.metadata, before.metadata)

        # The corpus followed the save (ADR-0085 §1): the next query finds the
        # new word and exactly one remaining occurrence of the old one.
        self.assertEqual(len(self._body_hits("aetherion")), 1)
        self.assertEqual(len(self._body_hits("aetheria")), 1)


class ReplaceAllHitsInOneNodeTests(SearchReplaceTestCase):
    def test_both_hits_replaced_highest_offset_first_longer_replacement(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)
        self.assertEqual(len(hits), 2, hits)

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(h) for h in hits]))

        self.assertTrue(all(o.status == "replaced" for o in response.outcomes), response.outcomes)
        self.assertEqual(response.replaced_nodes, 1)
        after = self.service.read_scene(scene_id)
        self.assertEqual(after.body, "Aetherion rose. Aetherion fell.\n")

    def test_both_hits_replaced_shorter_replacement(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)

        response = self.service.replace(ReplaceRequest(replacement="Ae", hits=[_hit_ref(h) for h in hits]))

        self.assertTrue(all(o.status == "replaced" for o in response.outcomes), response.outcomes)
        after = self.service.read_scene(scene_id)
        self.assertEqual(after.body, "Ae rose. Ae fell.\n")


class EmptyReplacementDeletesTests(SearchReplaceTestCase):
    def test_empty_replacement_deletes_the_matches(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)

        response = self.service.replace(ReplaceRequest(replacement="", hits=[_hit_ref(h) for h in hits]))

        self.assertTrue(all(o.status == "replaced" for o in response.outcomes), response.outcomes)
        after = self.service.read_scene(scene_id)
        self.assertEqual(after.body, " rose.  fell.\n")


class StaleTests(SearchReplaceTestCase):
    def test_edit_between_search_and_replace_makes_every_hit_stale(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)
        self.assertEqual(len(hits), 2, hits)

        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(title="Scene", body="Completely different text.", base_revision=current.revision),
        )
        after_second_save = self.service.read_scene(scene_id)

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(h) for h in hits]))

        self.assertEqual(len(response.outcomes), 2)
        self.assertTrue(all(o.status == "stale" and o.reason == "changed" for o in response.outcomes), response.outcomes)
        self.assertEqual(response.replaced_nodes, 0)
        unchanged = self.service.read_scene(scene_id)
        self.assertEqual(unchanged.body, after_second_save.body)
        self.assertEqual(unchanged.revision, after_second_save.revision)


class MovedTextTests(SearchReplaceTestCase):
    def test_tampered_text_with_correct_revision_is_stale(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)
        hit = hits[0]
        tampered = ReplaceHitRef(
            file_id=hit.file_id, field=hit.field, start=hit.start, end=hit.end,
            text="Aetherix", revision=hit.revision,
        )

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[tampered]))

        self.assertEqual(response.outcomes[0].status, "stale")
        self.assertEqual(response.outcomes[0].reason, "changed")
        self.assertEqual(response.replaced_nodes, 0)
        unchanged = self.service.read_scene(scene_id)
        self.assertEqual(unchanged.body, "Aetheria rose. Aetheria fell.\n")


class MetadataHitTests(SearchReplaceTestCase):
    def test_metadata_hit_is_not_replaceable_body_hit_on_same_node_still_replaces(self) -> None:
        scene_id = self._new_scene("Aetheria Notes", "Aetheria appears here")
        hits = self._search("aetheria")
        meta_hit = next(h for h in hits if h.field == "metadata")
        body_hit = next(h for h in hits if h.field == "body")

        response = self.service.replace(
            ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(meta_hit), _hit_ref(body_hit)])
        )

        outcomes_by_status = {o.status for o in response.outcomes}
        self.assertIn("not_replaceable", outcomes_by_status)
        self.assertIn("replaced", outcomes_by_status)
        meta_outcome = next(o for o in response.outcomes if o.status == "not_replaceable")
        self.assertEqual(meta_outcome.reason, "metadata")
        self.assertEqual(response.replaced_nodes, 1)

        after = self.service.read_scene(scene_id)
        self.assertEqual(after.body, "Aetherion appears here\n")
        # The title (the metadata hit's field) is untouched by the refusal.
        self.assertEqual(after.title, "Aetheria Notes")


class InheritedReplaceTests(unittest.TestCase):
    """Chain fixture (mirrors `InheritedLoreTests` / `OverrideRevisionRefreshTests`):
    universe > series > book. An ancestor lore hit is `not_replaceable/inherited`
    whether or not a root-layer override sits on top of it — the corpus flag and
    the live index must both agree (ADR-0085 §4 rule 1), and Acceptance 5's
    revision-agreement clause holds even with the override in place.
    """

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
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _write_ancestor_lore(self, folder: Path, node_id: str, title: str, body: str) -> None:
        (folder / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            folder / "lore" / f"{node_id}.md", node_id, title, "lore:note", {}, body
        )

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def test_inherited_hit_is_not_replaceable_and_file_untouched(self) -> None:
        self._write_ancestor_lore(self.universe, "ancestor_note", "Ancestor", "Aetheria, long ago")
        ancestor_path = self.universe / "lore" / "ancestor_note.md"
        before = ancestor_path.read_text(encoding="utf-8")

        hits = [h for h in self.service.search(SearchRequest(query="aetheria")).hits if h.field == "body"]
        hit = next(h for h in hits if h.file_id == "ancestor_note")

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(hit)]))

        self.assertEqual(len(response.outcomes), 1)
        self.assertEqual(response.outcomes[0].status, "not_replaceable")
        self.assertEqual(response.outcomes[0].reason, "inherited")
        self.assertEqual(response.replaced_nodes, 0)
        self.assertEqual(ancestor_path.read_text(encoding="utf-8"), before)

    def test_inherited_hit_with_a_root_override_is_still_not_replaceable_and_revision_agrees(self) -> None:
        self._write_ancestor_lore(self.universe, "ancestor_note", "Ancestor", "Aetheria, long ago")
        self.service.save_lore_entry(
            "ancestor_note",
            SaveLoreEntryRequest(
                title="Ancestor",
                body="Aetheria, long ago",
                entry_type="lore:note",
                metadata={"aliases": ["Ancestor Alt"]},
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))

        hits = [h for h in self.service.search(SearchRequest(query="aetheria")).hits if h.field == "body"]
        hit = next(h for h in hits if h.file_id == "ancestor_note")

        index = self.service._build_node_index(self.root)
        path = self.service._path_for_node_id("ancestor_note", "lore")
        expected_revision = self.service._composite_revision(
            [path, *self.service._override_paths_for_target(index, "ancestor_note")]
        )
        self.assertEqual(hit.revision, expected_revision)

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(hit)]))

        self.assertEqual(response.outcomes[0].status, "not_replaceable")
        self.assertEqual(response.outcomes[0].reason, "inherited")
        self.assertEqual(response.replaced_nodes, 0)

    def test_owned_prompt_with_a_leftover_override_replaces_with_the_corpus_revision(self) -> None:
        # #1850 end to end: the book overrode a series prompt, then the prompt moved
        # into the book and the override file stayed behind, still targeting an id
        # the book now OWNS. Corpus revision, read revision and the owned save's
        # conflict check must all be the same composite, or the replace is `stale`
        # forever (the save used to check the plain file revision).
        (self.series / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            self.series / "prompts" / "revise.md",
            "revise",
            "Revise plotline",
            "prompt:general",
            {"color": "slate"},
            "Aetheria needs revising.",
            extra={"inputs": []},
            omit_empty_metadata=True,
        )
        self.service.save_prompt_entry(
            "revise",
            SavePromptEntryRequest(
                title="Revise plotline",
                body="Aetheria needs revising.",
                entry_type="prompt:general",
                metadata={"color": "amber"},
            ),
        )
        self.assertTrue(any((self.root / OVERRIDES_FOLDER).glob("*.md")))
        (self.root / "prompts").mkdir(exist_ok=True)
        shutil.move(self.series / "prompts" / "revise.md", self.root / "prompts" / "revise.md")
        node_index_gate.invalidate()

        opened = self.service.read_prompt_entry("revise")
        self.assertTrue(opened.editable)
        self.assertNotEqual(opened.revision, self.service._revision(self.root / "prompts" / "revise.md"))
        hit = next(
            h
            for h in self.service.search(SearchRequest(query="aetheria")).hits
            if h.file_id == "revise" and h.field == "body"
        )
        self.assertEqual(hit.revision, opened.revision)
        self.assertTrue(hit.owned)

        response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(hit)]))

        self.assertEqual(response.outcomes[0].status, "replaced")
        self.assertEqual(response.replaced_nodes, 1)
        after = self.service.read_prompt_entry("revise")
        self.assertEqual(after.body.strip(), "Aetherion needs revising.")
        self.assertEqual(after.revision, response.outcomes[0].revision)


class UndispatchedKindTests(SearchReplaceTestCase):
    def test_assistant_and_chat_kinds_have_no_dispatch(self) -> None:
        self.assertIsNone(self.service._replace_dispatch_for("assistant", "assistant:assistant"))
        self.assertIsNone(self.service._replace_dispatch_for("chat", "chat:session"))

    def test_tag_metadata_hit_is_not_replaceable_tags_never_have_body_hits(self) -> None:
        tag = self.service.create_tag_entry(CreateTagEntryRequest(title="Aetheria Tag"))

        hits = self.service.search(SearchRequest(query="aetheria")).hits
        tag_hits = [h for h in hits if h.file_id == tag.id]
        self.assertTrue(tag_hits, hits)
        self.assertTrue(all(h.field == "metadata" for h in tag_hits), tag_hits)

        response = self.service.replace(
            ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(h) for h in tag_hits])
        )

        self.assertTrue(
            all(o.status == "not_replaceable" and o.reason == "metadata" for o in response.outcomes),
            response.outcomes,
        )
        self.assertEqual(response.replaced_nodes, 0)


class SavePrimitiveIsWritePathTests(SearchReplaceTestCase):
    """Acceptance 5: an owned body replace goes through the kind's own save
    primitive, asserted by spying the primitive — not the file."""

    def test_save_scene_called_exactly_once_for_a_two_hit_node(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)
        refs = [_hit_ref(h) for h in hits]

        with patch.object(ProjectService, "save_scene", wraps=self.service.save_scene) as spy:
            response = self.service.replace(ReplaceRequest(replacement="Aetherion", hits=refs))

        spy.assert_called_once()
        self.assertTrue(all(o.status == "replaced" for o in response.outcomes), response.outcomes)

    def test_atomic_write_happens_exactly_once_for_the_node(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose. Aetheria fell.")
        hits = self._body_hits("aetheria", scene_id)
        refs = [_hit_ref(h) for h in hits]

        with patch.object(ProjectService, "_atomic_write", wraps=self.service._atomic_write) as spy:
            self.service.replace(ReplaceRequest(replacement="Aetherion", hits=refs))

        spy.assert_called_once()


class EveryReplaceableKindRoundTripsTests(SearchReplaceTestCase):
    def _replace_only_hit(self, node_id: str, replacement: str = "Aetherion"):
        hits = self._body_hits("aetheria", node_id)
        self.assertEqual(len(hits), 1, hits)
        response = self.service.replace(ReplaceRequest(replacement=replacement, hits=[_hit_ref(hits[0])]))
        self.assertEqual(response.outcomes[0].status, "replaced", response.outcomes[0])
        return response

    def test_research_note_round_trips(self) -> None:
        tree = self.service.create_research_node(
            CreateStructureNodeRequest(title="Topic", entry_type="research:note")
        )
        note = next(child for child in tree.root.children if child.type == "research:note")
        note_id = note.scene_id
        self.service.save_research_note(note_id, SaveResearchNoteRequest(title="Topic", body="Aetheria research note"))
        before = self.service.read_research_note(note_id)

        self._replace_only_hit(note_id)

        after = self.service.read_research_note(note_id)
        self.assertEqual(after.body, "Aetherion research note\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.entry_type, before.entry_type)
        self.assertEqual(after.metadata, before.metadata)

    def test_prompt_round_trips_inputs_and_offer_on(self) -> None:
        prompt = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Prompt A", entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            prompt.id,
            SavePromptEntryRequest(
                title="Prompt A",
                body="Aetheria prompt body",
                base_revision=prompt.revision,
                entry_type="prompt:general",
                inputs=[PromptInputDefinition(name="topic")],
                offer_on=["manuscript:scene"],
            ),
        )
        before = self.service.read_prompt_entry(prompt.id)

        self._replace_only_hit(prompt.id)

        after = self.service.read_prompt_entry(prompt.id)
        self.assertEqual(after.body, "Aetherion prompt body\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.inputs, before.inputs)
        self.assertEqual(after.offer_on, before.offer_on)
        self.assertEqual(after.metadata, before.metadata)

    def test_plot_card_round_trips(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Card A"))
        self.service.save_card(
            card.id, SaveCardRequest(title="Card A", body="Aetheria card body", base_revision=card.revision)
        )
        before = self.service.read_card(card.id)

        self._replace_only_hit(card.id)

        after = self.service.read_card(card.id)
        self.assertEqual(after.body, "Aetherion card body\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.entry_type, before.entry_type)
        self.assertEqual(after.metadata, before.metadata)

    def test_plotline_round_trips(self) -> None:
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Plotline A"))
        self.service.save_plotline(
            plotline.id,
            SavePlotlineRequest(title="Plotline A", body="Aetheria plotline body", base_revision=plotline.revision),
        )
        before = self.service.read_plotline(plotline.id)

        self._replace_only_hit(plotline.id)

        after = self.service.read_plotline(plotline.id)
        self.assertEqual(after.body, "Aetherion plotline body\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.metadata, before.metadata)

    def test_character_arc_round_trips(self) -> None:
        arc = self.service.create_character_arc(CreateCharacterArcRequest(title="Arc A"))
        self.service.save_character_arc(
            arc.id, SaveCharacterArcRequest(title="Arc A", body="Aetheria arc body", base_revision=arc.revision)
        )
        before = self.service.read_character_arc(arc.id)

        self._replace_only_hit(arc.id)

        after = self.service.read_character_arc(arc.id)
        self.assertEqual(after.body, "Aetherion arc body\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.metadata, before.metadata)

    def test_plot_template_round_trips(self) -> None:
        template = self.service.create_plot_template(CreatePlotTemplateRequest(title="Template A"))
        self.service.save_plot_template(
            template.id,
            SavePlotTemplateRequest(
                title="Template A",
                body="Aetheria template body",
                template=template.template,
                base_revision=template.revision,
            ),
        )
        before = self.service.read_plot_template(template.id)

        self._replace_only_hit(template.id)

        after = self.service.read_plot_template(template.id)
        self.assertEqual(after.body, "Aetherion template body\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.metadata, before.metadata)
        self.assertEqual(after.template, before.template)

    def test_project_node_round_trips(self) -> None:
        node = self.service.read_project_node()
        self.service.save_project_node(
            SaveProjectNodeRequest(
                title=node.title,
                body="Aetheria project blurb",
                base_revision=node.revision,
                metadata={"author": "Ada"},
            )
        )
        before = self.service.read_project_node()

        self._replace_only_hit(before.id)

        after = self.service.read_project_node()
        self.assertEqual(after.body, "Aetherion project blurb\n")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.entry_type, before.entry_type)
        self.assertEqual(after.metadata, before.metadata)
        self.assertNotEqual(after.revision, before.revision)


class OverlapTests(SearchReplaceTestCase):
    def test_hand_built_overlapping_hits_are_not_replaceable(self) -> None:
        scene_id = self._new_scene("Scene", "Aetheria rose.")
        [hit] = self._body_hits("aetheria", scene_id)
        # Two hand-built refs over the same node whose ranges overlap.
        first = ReplaceHitRef(
            file_id=hit.file_id, field="body", start=hit.start, end=hit.start + 5, text="Aeth", revision=hit.revision
        )
        second = ReplaceHitRef(
            file_id=hit.file_id, field="body", start=hit.start + 2, end=hit.end, text="theria", revision=hit.revision
        )

        response = self.service.replace(ReplaceRequest(replacement="X", hits=[first, second]))

        self.assertTrue(
            all(o.status == "not_replaceable" and o.reason == "overlap" for o in response.outcomes), response.outcomes
        )
        self.assertEqual(response.replaced_nodes, 0)
        unchanged = self.service.read_scene(scene_id)
        self.assertEqual(unchanged.body, "Aetheria rose.\n")


class SaveRejectionIsNodeOutcomeTests(SearchReplaceTestCase):
    """A save that refuses the new content (a non-409 `ProjectServiceError`,
    e.g. a 422 from `validate_scene_markdown`) is that node's outcome, not an
    exception — earlier nodes in the same batch stay written."""

    def test_second_nodes_save_rejection_does_not_orphan_the_first_nodes_write(self) -> None:
        scene_a = self._new_scene("Scene A", "Aetheria rose.")
        scene_b = self._new_scene("Scene B", "Aetheria fell.")
        hit_a = self._body_hits("aetheria", scene_a)[0]
        hit_b = self._body_hits("aetheria", scene_b)[0]

        real_save_scene = self.service.save_scene

        def side_effect(scene_id, request):
            if scene_id == scene_a:
                return real_save_scene(scene_id, request)
            raise ProjectServiceError("no", 422)

        with patch.object(ProjectService, "save_scene", side_effect=side_effect) as _spy:
            response = self.service.replace(
                ReplaceRequest(replacement="Aetherion", hits=[_hit_ref(hit_a), _hit_ref(hit_b)])
            )

        self.assertEqual(response.replaced_nodes, 1)
        outcome_a = next(o for o in response.outcomes if o.file_id == scene_a)
        outcome_b = next(o for o in response.outcomes if o.file_id == scene_b)
        self.assertEqual(outcome_a.status, "replaced")
        self.assertIsNotNone(outcome_a.revision)
        self.assertEqual(outcome_b.status, "not_replaceable")
        self.assertEqual(outcome_b.reason, "rejected")
        self.assertEqual(outcome_b.detail, "no")

        after_a = self.service.read_scene(scene_a)
        after_b = self.service.read_scene(scene_b)
        self.assertEqual(after_a.body, "Aetherion rose.\n")
        self.assertEqual(after_b.body, "Aetheria fell.\n")

    def test_raw_html_replacement_is_genuinely_rejected_by_the_scenes_own_save(self) -> None:
        # A real trigger, not a patched one: `validate_scene_markdown` refuses
        # raw HTML, so a replacement that introduces it is refused by the
        # scene's own save, and that refusal becomes this node's outcome.
        scene_id = self._new_scene("Scene", "Aetheria rose.")
        [hit] = self._body_hits("aetheria", scene_id)

        response = self.service.replace(ReplaceRequest(replacement="<b>x</b>", hits=[_hit_ref(hit)]))

        self.assertEqual(len(response.outcomes), 1)
        outcome = response.outcomes[0]
        self.assertEqual(outcome.status, "not_replaceable")
        self.assertEqual(outcome.reason, "rejected")
        self.assertIn("raw HTML", outcome.detail or "")
        self.assertEqual(response.replaced_nodes, 0)
        unchanged = self.service.read_scene(scene_id)
        self.assertEqual(unchanged.body, "Aetheria rose.\n")


class RouteTests(unittest.TestCase):
    """`POST /api/search/replace` returns 200 with outcomes even for a stale
    hit — never a 409 (a mixed batch has no single status, ADR-0085 §4)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Route Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stale_hit_returns_200_with_a_stale_outcome(self) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Scene"))
        self.service.save_scene(
            scene.id, SaveSceneRequest(title="Scene", body="Aetheria rose.", base_revision=scene.revision)
        )
        current = self.service.read_scene(scene.id)
        self.service.save_scene(
            scene.id, SaveSceneRequest(title="Scene", body="Different now.", base_revision=current.revision)
        )

        response = self.client.post(
            "/api/search/replace",
            json={
                "replacement": "Aetherion",
                "hits": [
                    {
                        "file_id": scene.id,
                        "field": "body",
                        "start": 0,
                        "end": len("Aetheria"),
                        "text": "Aetheria",
                        "revision": current.revision,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["outcomes"]), 1)
        self.assertEqual(body["outcomes"][0]["status"], "stale")
        self.assertEqual(body["replaced_nodes"], 0)


if __name__ == "__main__":
    unittest.main()
