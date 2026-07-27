from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

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
from app.models_plot import (
    PlotTemplateInstanceSpec,
    PlotTemplateSpec,
)
from app.services.project_service import ProjectService


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
            entry
            for entry in response.json()["entries"]
            if entry["entry_type"] == "plot:template"
        ]
        expected_template_ids = {
            "plot_template_three_act",
            "plot_template_fifteen_beat_transformation",
            "plot_template_mythic_quest",
            "plot_template_twelve_step_quest",
            "plot_template_heroine_journey",
            "plot_template_circular_change",
            "plot_template_seven_point",
            "plot_template_kishotenketsu",
            "plot_template_romance_relationship",
            "plot_template_mystery_spine",
            "plot_template_thriller_escalation",
            "plot_template_positive_character_change",
            "plot_template_negative_character_change",
            "plot_template_steadfast_character",
        }
        self.assertTrue(
            expected_template_ids.issubset({entry["id"] for entry in templates})
        )
        self.assertTrue(all(entry["system"] for entry in templates))

        node = self.client.get("/api/plots/plot_template_seven_point").json()
        self.assertEqual(node["entry_type"], "plot:template")
        self.assertTrue(node["system"])
        self.assertEqual(node["template"]["family"], "act")
        self.assertEqual(node["template"]["builtin_policy"], "seed_generic")
        midpoint = next(
            point
            for point in node["template"]["plot_points"]
            if point["id"] == "midpoint_shift"
        )
        self.assertEqual(
            midpoint["function_claim"],
            "Moves the protagonist from reaction toward action.",
        )
        self.assertNotIn("placement", midpoint)
        self.assertNotIn("compression", midpoint)
        self.assertNotIn("ai_rubric", midpoint)

    def test_open_project_backfills_missing_builtin_templates(self) -> None:
        for path in (self.root / "plot").glob("*.md"):
            path.unlink()

        reopened = ProjectService.opened_at(self.root)
        templates = [
            entry
            for entry in reopened.list_plot_nodes().entries
            if entry.entry_type == "plot:template"
        ]
        self.assertGreaterEqual(len(templates), 14)
        self.assertTrue(all(entry.system for entry in templates))

    def test_open_project_refreshes_sparse_system_builtin_templates(self) -> None:
        (self.root / "plot" / "Three Act Structure.md").write_text(
            """---
id: plot_template_three_act
title: Three Act Structure
entry_type: plot:template
system: true
template:
  slug: three-act-structure
  display_name: Three Act Structure
  family: act
  plot_points:
    - id: first_turn
      title: First turn
      function_claim: Old sparse claim.
---
Old sparse body.
""",
            encoding="utf-8",
        )

        reopened = ProjectService.opened_at(self.root)
        node = reopened.read_plot_node("plot_template_three_act")

        self.assertEqual(node.title, "Three-Act Story Arc")
        self.assertEqual(node.template.display_name, "Three-Act Story Arc")
        self.assertIn("## How To Use It", node.body)
        self.assertIn("## Beat Logic", node.body)
        self.assertNotIn("Old sparse body.", node.body)
        self.assertLess(len(node.template.description), 160)
        point_ids = {point.id for point in node.template.plot_points}
        self.assertIn("inciting_change", point_ids)
        first_point = node.template.plot_points[0]
        self.assertEqual(first_point.id, "setup_pressure")
        self.assertEqual(
            first_point.function_claim,
            "Establishes ordinary conditions, desire, and pressure before commitment.",
        )

    def test_system_template_rejects_save_and_delete(self) -> None:
        templates = self.client.get("/api/plots").json()["entries"]
        template = next(
            entry for entry in templates if entry["entry_type"] == "plot:template"
        )
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
                "nodes": [
                    {
                        "id": "card_archive",
                        "kind": "card",
                        "position": {"x": 20, "y": 40},
                        "cfg": {},
                    }
                ],
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
                    "enabled_point_ids": ["first_turn"],
                    "plot_points": [
                        {"plot_point_id": "first_turn", "notes": "The archive theft."}
                    ],
                    "point_notes": {
                        "first_turn": {
                            "status": "planned",
                            "author_intent": "Mara commits by stealing the ledger.",
                            "open_questions": ["Who sees her leave?"],
                        }
                    },
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertEqual(body["body"], "Book-specific notes.")
        self.assertEqual(
            body["template_instance"]["template_id"], "plot_template_three_act"
        )
        self.assertEqual(body["template_instance"]["enabled_point_ids"], ["first_turn"])
        note = body["template_instance"]["point_notes"]["first_turn"]
        self.assertEqual(note["status"], "planned")
        self.assertEqual(note["author_intent"], "Mara commits by stealing the ledger.")
        self.assertEqual(note["open_questions"], ["Who sees her leave?"])

    def test_plot_template_contract_accepts_design_doc_names(self) -> None:
        template = PlotTemplateSpec.model_validate(
            {
                "slug": "three-act",
                "display_name": "Three Act",
                "family": "act",
                "source_refs": [{"id": "src", "title": "Generic craft note"}],
                "ip_risk": "low",
                "builtin_policy": "seed_generic",
                "points": [
                    {
                        "id": "first_turn",
                        "key": "first_turn",
                        "order_index": 2,
                        "label": "First Turning Point",
                        "function": {"claim": "Makes the old path unavailable."},
                        "placement": {"phase_label": "Act I"},
                        "compression": {"can_compress": True},
                        "ai_rubric": {"criteria": ["Cites evidence."]},
                    }
                ],
            }
        )

        self.assertEqual(template.plot_points[0].title, "First Turning Point")
        self.assertEqual(
            template.plot_points[0].function_claim, "Makes the old path unavailable."
        )
        dumped = template.model_dump()
        self.assertNotIn("placement", dumped["plot_points"][0])
        self.assertNotIn("compression", dumped["plot_points"][0])
        self.assertNotIn("ai_rubric", dumped["plot_points"][0])

        instance = PlotTemplateInstanceSpec.model_validate(
            {
                "template_ref": "plot_template_three_act",
                "enabled_point_ids": ["first_turn"],
                "point_notes": {
                    "first_turn": {
                        "local_label": "Archive turn",
                        "status": "planned",
                        "author_intent": "Mara chooses theft over duty.",
                        "open_questions": ["What does this cost her?"],
                    }
                },
            }
        )
        self.assertEqual(instance.template_id, "plot_template_three_act")
        self.assertEqual(instance.plot_points[0].plot_point_id, "first_turn")
        self.assertEqual(instance.plot_points[0].status, "planned")
        self.assertEqual(
            instance.point_notes["first_turn"].author_intent,
            "Mara chooses theft over duty.",
        )

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
        self.assertEqual(
            payload["plot"]["board"]["claims"][0]["card_id"], "card_archive"
        )

        persisted = self.client.get(f"/api/plots/{board['id']}").json()
        self.assertEqual(persisted["board"]["cards"][0]["node_ref"], scene["id"])
        self.assertEqual(
            self.client.get(f"/api/scenes/{scene['id']}").json()["title"],
            "Archive Break-in",
        )

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
        self.assertEqual(
            [claim["id"] for claim in context["cards"][0]["claims"]],
            ["claim_first_turn"],
        )
        self.assertEqual(
            [claim["id"] for claim in context["claims"]], ["claim_first_turn"]
        )
        self.assertEqual(context["cards"][0]["primary_plotline"]["title"], "Main")
        self.assertEqual(context["claims"][0]["plotline"]["title"], "Main")
        self.assertEqual(
            context["claims"][0]["card"]["title"],
            "Archive Break-in",
        )
        context_points = context["template_instances"][0]["plot_points"]
        context_point_ids = [point["plot_point_id"] for point in context_points]
        self.assertIn("inciting_change", context_point_ids)
        self.assertIn("first_turn", context_point_ids)
        self.assertIn("resolution", context_point_ids)
        first_turn_point = next(
            point for point in context_points if point["plot_point_id"] == "first_turn"
        )
        self.assertEqual(
            [claim["id"] for claim in first_turn_point["claims"]],
            ["claim_first_turn"],
        )
        self.assertEqual(
            first_turn_point["claims"][0]["card"]["title"],
            "Archive Break-in",
        )
        resolution_point = next(
            point for point in context_points if point["plot_point_id"] == "resolution"
        )
        self.assertEqual(resolution_point["notes"], "")
        self.assertEqual(resolution_point["claims"], [])
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
        self.assertEqual(
            [claim["id"] for card in future_context["cards"] for claim in card["claims"]],
            ["claim_first_turn", "claim_resolution"],
        )
        future_points = future_context["template_instances"][0]["plot_points"]
        future_resolution = next(
            point for point in future_points if point["plot_point_id"] == "resolution"
        )
        self.assertEqual(
            [claim["id"] for claim in future_resolution["claims"]],
            ["claim_resolution"],
        )

    def test_plot_context_resolves_design_shaped_template_instance_contract(
        self,
    ) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        template = self.client.post(
            "/api/plots",
            json={
                "title": "Local Structure",
                "entry_type": "plot:template",
                "template": {
                    "slug": "local-structure",
                    "display_name": "Local Structure",
                    "family": "act",
                    "description": "A local diagnostic lens.",
                    "ai_use_guidance": "Ask for evidence before claiming satisfaction.",
                    "global_diagnostic_questions": ["What pressure changes?"],
                    "source_refs": [{"id": "src", "title": "Local note"}],
                    "ip_risk": "low",
                    "builtin_policy": "user_authored",
                    "points": [
                        {
                            "id": "first_turn",
                            "label": "First Turning Point",
                            "function": {"claim": "Makes the old path unavailable."},
                            "placement": {"phase_label": "Act I"},
                            "compression": {"can_compress": True},
                            "ai_rubric": {"criteria": ["Cite a card."]},
                            "diagnostic_questions": [
                                "What decision closes the old path?"
                            ],
                        }
                    ],
                },
            },
        ).json()
        instance = self.client.post(
            "/api/plots",
            json={
                "title": "Main Structure",
                "entry_type": "plot:template_instance",
                "template_instance": {
                    "template_ref": template["id"],
                    "enabled_point_ids": ["first_turn"],
                    "point_notes": {
                        "first_turn": {
                            "local_label": "Archive commitment",
                            "status": "planned",
                            "author_intent": "Mara chooses theft over duty.",
                            "open_questions": ["Who catches the clue?"],
                        }
                    },
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
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": scene.id,
                        }
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance["id"],
                            "plot_point_id": "first_turn",
                        }
                    ],
                },
            },
        ).json()

        context = self.client.get(
            f"/api/plots/{board['id']}/context",
            params={"scene_id": scene.id},
        ).json()

        context_instance = context["template_instances"][0]
        self.assertEqual(context_instance["template_slug"], "local-structure")
        self.assertEqual(context_instance["template_family"], "act")
        self.assertEqual(
            context_instance["ai_use_guidance"],
            "Ask for evidence before claiming satisfaction.",
        )
        context_point = context_instance["plot_points"][0]
        self.assertEqual(context_point["title"], "Archive commitment")
        self.assertEqual(context_point["status"], "planned")
        self.assertEqual(
            context_point["author_intent"], "Mara chooses theft over duty."
        )
        self.assertEqual(context_point["open_questions"], ["Who catches the clue?"])
        self.assertEqual(
            context_point["function_claim"], "Makes the old path unavailable."
        )
        self.assertNotIn("placement", context_point)
        self.assertNotIn("compression", context_point)
        self.assertNotIn("ai_rubric", context_point)

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
