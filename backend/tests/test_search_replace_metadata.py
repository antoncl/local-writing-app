"""Tests for replacing inside stored free-text metadata (ADR-0085 Amendment 2,
#2641): a scene's `summary`, a card's `follow_ups` items, a plotline beat's
text members — anchored hits that replace through the node's own save, while
titles, references and identity members stay find-only.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import (
    CreateCardRequest,
    CreatePlotlineRequest,
    CreateSceneRequest,
    RealizeCardRequest,
    ReplaceHitRef,
    ReplaceRequest,
    SaveCardRequest,
    SavePlotlineRequest,
    SaveSceneRequest,
    SearchHit,
    SearchRequest,
)
from app.services.project.metadata_text import iter_text_slots
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService


def _hit_ref(hit: SearchHit) -> ReplaceHitRef:
    return ReplaceHitRef(
        file_id=hit.file_id,
        field=hit.field,
        start=hit.start,
        end=hit.end,
        text=hit.text,
        revision=hit.revision,
        metadata_path=hit.metadata_path,
    )


class MetadataReplaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Test Project")
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    def _hits(self, query: str, file_id: str) -> list[SearchHit]:
        return [h for h in self.service.search(SearchRequest(query=query)).hits if h.file_id == file_id]

    def _replace_all(self, query: str, file_id: str, replacement: str = "Coma"):
        hits = self._hits(query, file_id)
        return self.service.replace(ReplaceRequest(replacement=replacement, hits=[_hit_ref(h) for h in hits]))

    def _scene(self, title: str, body: str, metadata: dict) -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title=title, body=body, base_revision=scene.revision, metadata=metadata),
        )
        return scene.id


class SceneSummaryTests(MetadataReplaceTestCase):
    def test_summary_hit_is_anchored_and_replaced_on_disk(self) -> None:
        scene_id = self._scene(
            "Arrival",
            "Halvik walked in.",
            {"summary": "Halvik reaches the flat. The guard waves Halvik through."},
        )

        hits = [h for h in self._hits("halvik", scene_id) if h.field == "metadata"]
        self.assertEqual([h.metadata_path for h in hits], [["summary"], ["summary"]], hits)
        self.assertEqual([(h.start, h.end, h.text) for h in hits], [(0, 6, "Halvik"), (41, 47, "Halvik")])

        response = self._replace_all("halvik", scene_id)

        self.assertTrue(all(o.status == "replaced" for o in response.outcomes), response.outcomes)
        self.assertEqual(response.replaced_nodes, 1)
        after = self.service.read_scene(scene_id)
        self.assertEqual(after.metadata["summary"], "Coma reaches the flat. The guard waves Coma through.")
        self.assertEqual(after.body, "Coma walked in.\n")
        text = next((self.root / "scenes").glob("*.md")).read_text(encoding="utf-8")
        self.assertNotIn("Halvik", text)
        self.assertEqual(self._hits("halvik", scene_id), [])

    def test_title_stays_find_only_beside_a_replaced_summary(self) -> None:
        scene_id = self._scene("Halvik arrives", "", {"summary": "Halvik reaches the flat."})

        response = self._replace_all("halvik", scene_id)

        by_status = {(o.status, o.reason) for o in response.outcomes}
        self.assertEqual(by_status, {("replaced", None), ("not_replaceable", "metadata")})
        after = self.service.read_scene(scene_id)
        self.assertEqual(after.title, "Halvik arrives")
        self.assertEqual(after.metadata["summary"], "Coma reaches the flat.")

    def test_summary_edited_after_search_is_stale_and_unwritten(self) -> None:
        scene_id = self._scene("Arrival", "", {"summary": "Halvik reaches the flat."})
        hits = self._hits("halvik", scene_id)
        current = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title="Arrival", body="", base_revision=current.revision, metadata={"summary": "Someone else."}
            ),
        )

        response = self.service.replace(ReplaceRequest(replacement="Coma", hits=[_hit_ref(h) for h in hits]))

        self.assertEqual([o.status for o in response.outcomes], ["stale"])
        self.assertEqual(self.service.read_scene(scene_id).metadata["summary"], "Someone else.")


class ListSlotTests(MetadataReplaceTestCase):
    def test_follow_up_items_on_a_written_card_are_replaced_its_body_is_not(self) -> None:
        card = self.service.create_card(CreateCardRequest(title="Card"))
        self.service.save_card(
            card.id, SaveCardRequest(title="Card", body="Halvik card body", base_revision=card.revision)
        )
        self.service.realize_card(card.id, RealizeCardRequest())
        written = self.service.read_card(card.id)
        self.service.save_card(
            card.id,
            SaveCardRequest(
                title="Card",
                body=written.body,
                base_revision=written.revision,
                metadata={**written.metadata, "follow_ups": ["Keep it", "Is Halvik's police there?"]},
            ),
        )

        response = self._replace_all("halvik", card.id)

        statuses = sorted((o.status, o.reason, tuple(o.metadata_path or ())) for o in response.outcomes)
        self.assertEqual(
            statuses,
            [("not_replaceable", "written", ()), ("replaced", None, ("follow_ups", 1))],
        )
        after = self.service.read_card(card.id)
        self.assertEqual(after.metadata["follow_ups"], ["Keep it", "Is Coma's police there?"])
        self.assertEqual(after.body, "Halvik card body\n")

    def test_group_text_members_are_replaced_identity_and_other_members_untouched(self) -> None:
        plotline = self.service.create_plotline(CreatePlotlineRequest(title="Line"))
        beat = {
            "id": "beat_halvik",
            "title": "Halvik arrives",
            "function": "",
            "guidance": "",
            "specifics": "Halvik meets the guard.",
            "required": True,
        }
        self.service.save_plotline(
            plotline.id,
            SavePlotlineRequest(
                title="Line", body="", base_revision=plotline.revision, metadata={"instance_beats": [beat]}
            ),
        )
        paths = sorted(tuple(h.metadata_path or ()) for h in self._hits("halvik", plotline.id))
        # The identity member's minted id matches too, but only as a find-only hit.
        self.assertEqual(paths, [(), ("instance_beats", 0, "specifics"), ("instance_beats", 0, "title")])

        response = self._replace_all("halvik", plotline.id)

        self.assertEqual(
            sorted((o.status, o.reason) for o in response.outcomes),
            [("not_replaceable", "metadata"), ("replaced", None), ("replaced", None)],
        )
        item = self.service.read_plotline(plotline.id).metadata["instance_beats"][0]
        self.assertEqual(item["id"], "beat_halvik")
        self.assertEqual(item["title"], "Coma arrives")
        self.assertEqual(item["specifics"], "Coma meets the guard.")
        self.assertIs(item["required"], True)


class TextSlotDefinitionTests(MetadataReplaceTestCase):
    def test_references_and_identity_members_are_not_slots(self) -> None:
        schema = self.service.read_metadata_schema()
        metadata = {
            "summary": "gist",
            "scene": "manuscript_abc",
            "instance_beats": [{"id": "beat_1", "title": "T", "required": True}],
            "follow_ups": ["one"],
        }

        slots = dict(iter_text_slots(metadata, schema))

        self.assertEqual(
            slots,
            {("summary",): "gist", ("instance_beats", 0, "title"): "T", ("follow_ups", 0): "one"},
        )


if __name__ == "__main__":
    unittest.main()
