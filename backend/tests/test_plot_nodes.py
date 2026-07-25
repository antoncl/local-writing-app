from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CreateSceneRequest,
    DeleteMetadataFieldRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    RenameMetadataFieldRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template
from app.models_plot import CreatePlotNodeRequest
from app.services.project_service import ProjectService
from project_fixtures import open_test_project


class PlotNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.service = open_test_project(self.root, "Plot Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_creation_seeds_readonly_templates(self) -> None:
        response = self.client.get("/api/plots")
        self.assertEqual(response.status_code, 200, response.text)
        templates = [
            entry for entry in response.json()["entries"]
            if entry["entry_type"] == "plot:template"
        ]
        self.assertGreaterEqual(len(templates), 3)
        self.assertTrue(all(entry["system"] for entry in templates))

        node = self.client.get(f"/api/plots/{templates[0]['id']}").json()
        self.assertEqual(node["entry_type"], "plot:template")
        self.assertTrue(node["system"])
        self.assertGreater(len(node["template"]["plot_points"]), 0)

    def test_open_project_backfills_missing_builtin_templates(self) -> None:
        for path in (self.root / "plot").glob("*.md"):
            path.unlink()

        reopened = ProjectService.opened_at(self.root)
        templates = [
            entry for entry in reopened.list_plot_nodes().entries
            if entry.entry_type == "plot:template"
        ]
        self.assertGreaterEqual(len(templates), 3)
        self.assertTrue(all(entry.system for entry in templates))

    def test_system_template_rejects_save_and_delete(self) -> None:
        templates = self.client.get("/api/plots").json()["entries"]
        template = next(entry for entry in templates if entry["entry_type"] == "plot:template")
        node = self.client.get(f"/api/plots/{template['id']}").json()

        save = self.client.put(
            f"/api/plots/{node['id']}",
            json={
                "title": "Edited",
                "entry_type": node["entry_type"],
                "body": node["body"],
                "base_revision": node["revision"],
                "template": node["template"],
            },
        )
        self.assertEqual(save.status_code, 403, save.text)

        delete = self.client.delete(f"/api/plots/{node['id']}")
        self.assertEqual(delete.status_code, 403, delete.text)

    def test_board_roundtrips_spec_and_layout(self) -> None:
        payload = {
            "title": "Book plot board",
            "entry_type": "plot:board",
            "metadata": {"color": "moss"},
            "board": {
                "template_instance_ids": ["plot_instance_main"],
                "plotlines": [{"id": "plotline_main", "title": "Main"}],
                "cards": [
                    {
                        "id": "card_archive",
                        "title": "Archive Break-in",
                        "synopsis": "Mara steals the ledger.",
                        "structure_column_id": "chapter_1",
                    }
                ],
                "claims": [
                    {
                        "id": "claim_first_turn",
                        "card_id": "card_archive",
                        "template_instance_id": "plot_instance_main",
                        "plot_point_id": "first_turn",
                        "claim_type": "satisfies",
                        "rationale": "The old path is unavailable.",
                    }
                ],
            },
            "layout": {
                "nodes": [{"id": "card_archive", "kind": "card", "position": {"x": 20, "y": 40}, "cfg": {}}],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 0.85},
            },
        }
        created = self.client.post("/api/plots", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertTrue(body["id"].startswith("plot_"))
        self.assertEqual(body["metadata"], {"color": "moss"})
        self.assertEqual(body["board"]["claims"][0]["plot_point_id"], "first_turn")
        self.assertEqual(body["layout"]["viewport"]["zoom"], 0.85)

        got = self.client.get(f"/api/plots/{body['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["metadata"], {"color": "moss"})
        self.assertEqual(got.json()["board"], body["board"])
        self.assertEqual(got.json()["layout"], body["layout"])

    def test_template_instance_roundtrips_body_and_template_ref(self) -> None:
        created = self.client.post(
            "/api/plots",
            json={
                "title": "Main plot structure",
                "entry_type": "plot:template_instance",
                "body": "Book-specific notes.",
                "template_instance": {
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "first_turn", "notes": "The archive theft."}],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertEqual(body["body"], "Book-specific notes.")
        self.assertEqual(body["template_instance"]["template_id"], "plot_template_three_act")

    def test_invalid_board_front_matter_is_rejected(self) -> None:
        (self.root / "plot" / "Broken Board.md").write_text(
            """---
id: plot_broken
title: Broken Board
entry_type: plot:board
board:
  cards:
    - id: ""
      title: Bad card
---
""",
            encoding="utf-8",
        )

        response = self.client.get("/api/plots/plot_broken")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("invalid board data", response.json()["detail"])

    def test_placeholder_card_can_be_promoted_to_scene(self) -> None:
        board = self.client.post(
            "/api/plots",
            json={
                "title": "Book plot board",
                "entry_type": "plot:board",
                "board": {
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                        }
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": "plot_instance_main",
                            "plot_point_id": "first_turn",
                            "claim_type": "satisfies",
                        }
                    ],
                },
            },
        ).json()

        response = self.client.post(
            f"/api/plots/{board['id']}/promote-card",
            json={"card_id": "card_archive", "base_revision": board["revision"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        scene = payload["scene"]
        self.assertEqual(scene["title"], "Archive Break-in")

        promoted_card = payload["plot"]["board"]["cards"][0]
        self.assertEqual(promoted_card["id"], "card_archive")
        self.assertEqual(promoted_card["node_ref"], scene["id"])
        self.assertEqual(payload["plot"]["board"]["claims"][0]["card_id"], "card_archive")

        persisted = self.client.get(f"/api/plots/{board['id']}").json()
        self.assertEqual(persisted["board"]["cards"][0]["node_ref"], scene["id"])
        self.assertEqual(self.client.get(f"/api/scenes/{scene['id']}").json()["title"], "Archive Break-in")

        def has_scene(node: dict) -> bool:
            if node.get("scene_id") == scene["id"]:
                return True
            return any(has_scene(child) for child in node.get("children", []))

        self.assertTrue(has_scene(payload["structure"]["root"]))

    def test_promoting_linked_plot_card_is_rejected(self) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        board = self.client.post(
            "/api/plots",
            json={
                "title": "Book plot board",
                "entry_type": "plot:board",
                "board": {
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": scene.id,
                        }
                    ],
                },
            },
        ).json()

        response = self.client.post(
            f"/api/plots/{board['id']}/promote-card",
            json={"card_id": "card_archive", "base_revision": board["revision"]},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_plot_context_omits_future_cards_claims_and_point_notes(self) -> None:
        early = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        target = self.service.create_scene(CreateSceneRequest(title="Quiet Aftermath"))
        future = self.service.create_scene(CreateSceneRequest(title="Butler Reveal"))
        instance = self.client.post(
            "/api/plots",
            json={
                "title": "Main plot structure",
                "entry_type": "plot:template_instance",
                "template_instance": {
                    "template_id": "plot_template_three_act",
                    "plot_points": [
                        {
                            "plot_point_id": "first_turn",
                            "notes": "Mara steals the ledger.",
                        },
                        {
                            "plot_point_id": "resolution",
                            "notes": "Future spoiler: the butler did it.",
                        },
                    ],
                },
            },
        ).json()
        board = self.client.post(
            "/api/plots",
            json={
                "title": "Book plot board",
                "entry_type": "plot:board",
                "board": {
                    "template_instance_ids": [instance["id"]],
                    "plotlines": [{"id": "plotline_main", "title": "Main"}],
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                            "node_ref": early.id,
                            "primary_plotline_id": "plotline_main",
                        },
                        {
                            "id": "card_reveal",
                            "title": "Butler Reveal",
                            "synopsis": "The butler confesses.",
                            "node_ref": future.id,
                            "primary_plotline_id": "plotline_main",
                        },
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance["id"],
                            "plot_point_id": "first_turn",
                            "plotline_id": "plotline_main",
                            "claim_type": "satisfies",
                            "rationale": "The old path is unavailable.",
                        },
                        {
                            "id": "claim_resolution",
                            "card_id": "card_reveal",
                            "template_instance_id": instance["id"],
                            "plot_point_id": "resolution",
                            "plotline_id": "plotline_main",
                            "claim_type": "satisfies",
                            "rationale": "Future spoiler: the butler did it.",
                        },
                    ],
                },
            },
        ).json()

        response = self.client.get(
            f"/api/plots/{board['id']}/context",
            params={"scene_id": target.id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        context = response.json()
        self.assertEqual([card["id"] for card in context["cards"]], ["card_archive"])
        self.assertEqual([claim["id"] for claim in context["claims"]], ["claim_first_turn"])
        self.assertEqual(context["omitted_counts"]["future_cards"], 1)
        self.assertNotIn("Butler Reveal", str(context))
        self.assertNotIn("butler did it", str(context))

        future_context = self.client.get(
            f"/api/plots/{board['id']}/context",
            params={"scene_id": future.id},
        ).json()
        self.assertEqual(
            [claim["id"] for claim in future_context["claims"]],
            ["claim_first_turn", "claim_resolution"],
        )

    def test_plot_context_helper_renders_scene_scoped_context(self) -> None:
        early = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        target = self.service.create_scene(CreateSceneRequest(title="Quiet Aftermath"))
        future = self.service.create_scene(CreateSceneRequest(title="Butler Reveal"))
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [
                        {"plot_point_id": "first_turn", "notes": "Visible setup."},
                        {"plot_point_id": "resolution", "notes": "Future spoiler: the butler did it."},
                    ],
                },
            )
        )
        board = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={
                    "template_instance_ids": [instance.id],
                    "cards": [
                        {"id": "card_archive", "title": "Archive Break-in", "node_ref": early.id},
                        {"id": "card_reveal", "title": "Butler Reveal", "node_ref": future.id},
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                        },
                        {
                            "id": "claim_resolution",
                            "card_id": "card_reveal",
                            "template_instance_id": instance.id,
                            "plot_point_id": "resolution",
                            "rationale": "Future spoiler: the butler did it.",
                        },
                    ],
                },
            )
        )
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ plot_context("' + board.id + '", scene=scene) }}{% endrole %}',
            context={"scene": target},
            env=env,
        )
        text = out.messages[0].blocks[0].text
        self.assertIn("Archive Break-in", text)
        self.assertIn("claim_first_turn", text)
        self.assertNotIn("Butler Reveal", text)
        self.assertNotIn("butler did it", text)

    def test_plot_context_helper_accepts_context_pick_board_ref(self) -> None:
        early = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        target = self.service.create_scene(CreateSceneRequest(title="Quiet Aftermath"))
        future = self.service.create_scene(CreateSceneRequest(title="Butler Reveal"))
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [
                        {"plot_point_id": "first_turn", "notes": "Visible setup."},
                        {"plot_point_id": "resolution", "notes": "Future spoiler: the butler did it."},
                    ],
                },
            )
        )
        board = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={
                    "template_instance_ids": [instance.id],
                    "cards": [
                        {"id": "card_archive", "title": "Archive Break-in", "node_ref": early.id},
                        {"id": "card_reveal", "title": "Butler Reveal", "node_ref": future.id},
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                        },
                        {
                            "id": "claim_resolution",
                            "card_id": "card_reveal",
                            "template_instance_id": instance.id,
                            "plot_point_id": "resolution",
                            "rationale": "Future spoiler: the butler did it.",
                        },
                    ],
                },
            )
        )
        picked_board = json.dumps(
            [
                {
                    "id": board.id,
                    "kind": "plot",
                    "title": board.title,
                    "entry_type": "plot:board",
                }
            ]
        )
        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ plot_context(input.board, scene=scene) }}{% endrole %}',
            context={"input": {"board": picked_board}, "scene": target},
            env=env,
        )
        text = out.messages[0].blocks[0].text
        self.assertIn("Archive Break-in", text)
        self.assertIn("claim_first_turn", text)
        self.assertNotIn("Butler Reveal", text)
        self.assertNotIn("butler did it", text)

    def test_plot_node_is_available_via_unified_node_read(self) -> None:
        created = self.client.post(
            "/api/plots",
            json={"title": "Unified board", "entry_type": "plot:board"},
        ).json()
        got = self.client.get(f"/api/nodes/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["entry_type"], "plot:board")

    def test_plot_entry_type_can_be_customised_in_project_schema(self) -> None:
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                entry_type_id="subplot_board",
                entry_type=EntryTypeDefinition(
                    name="Subplot board",
                    kind="plot",
                    parent="plot:board",
                    fields=[],
                ),
            )
        )

        self.assertIn("plot:subplot_board", schema.entry_types)
        self.assertEqual(schema.entry_types["plot:subplot_board"].kind, "plot")

        created = self.client.post(
            "/api/plots",
            json={"title": "Romance subplot", "entry_type": "plot:subplot_board"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["board"]["cards"], [])

    def test_schema_field_changes_update_plot_metadata_files(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="tension",
                field=MetadataFieldDefinition(name="Tension", type="text"),
                entry_type="plot:board",
            )
        )
        created = self.client.post(
            "/api/plots",
            json={
                "title": "Metadata board",
                "entry_type": "plot:board",
                "metadata": {"tension": "rising"},
            },
        ).json()

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(
                old_field_id="tension",
                new_field_id="pressure",
                entry_type="plot:board",
            )
        )
        renamed = self.client.get(f"/api/plots/{created['id']}").json()
        self.assertEqual(renamed["metadata"], {"pressure": "rising"})

        self.service.delete_metadata_field(
            DeleteMetadataFieldRequest(field_id="pressure", entry_type="plot:board")
        )
        deleted = self.client.get(f"/api/plots/{created['id']}").json()
        self.assertEqual(deleted["metadata"], {})


if __name__ == "__main__":
    unittest.main()
