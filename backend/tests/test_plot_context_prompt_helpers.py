from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import CreateSceneRequest
from app.models_plot import CreatePlotNodeRequest, PlotTemplateSpec
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template


class PlotContextPromptHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.service = open_test_project(self.root, "Plot Context Prompt Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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
                        {
                            "plot_point_id": "resolution",
                            "notes": "Future spoiler: the butler did it.",
                        },
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
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": early.id,
                        },
                        {
                            "id": "card_reveal",
                            "title": "Butler Reveal",
                            "node_ref": future.id,
                        },
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
            '{% role "user" %}{{ context_xml(plot_context("'
            + board.id
            + '", as_of=scene)) }}{% endrole %}',
            context={"scene": target},
            env=env,
        )
        text = out.messages[0].blocks[0].text
        self.assertIn('completeness="through_as_of"', text)
        self.assertIn(f'as_of_scene_id="{target.id}"', text)
        self.assertIn("Archive Break-in", text)
        self.assertIn("claim_first_turn", text)
        self.assertIn('card_title="Archive Break-in"', text)
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
                        {
                            "plot_point_id": "resolution",
                            "notes": "Future spoiler: the butler did it.",
                        },
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
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": early.id,
                        },
                        {
                            "id": "card_reveal",
                            "title": "Butler Reveal",
                            "node_ref": future.id,
                        },
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
            '{% role "user" %}{{ context_xml(plot_context(input.plot, as_of=scene)) }}{% endrole %}',
            context={"input": {"plot": picked_board}, "scene": target},
            env=env,
        )
        text = out.messages[0].blocks[0].text
        self.assertIn("Archive Break-in", text)
        self.assertIn("claim_first_turn", text)
        self.assertNotIn("Butler Reveal", text)
        self.assertNotIn("butler did it", text)

    def test_plot_context_without_as_of_renders_whole_selected_board(self) -> None:
        early = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        future = self.service.create_scene(CreateSceneRequest(title="Butler Reveal"))
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [
                        {"plot_point_id": "first_turn", "notes": "Visible setup."},
                        {"plot_point_id": "resolution", "notes": "Future reveal."},
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
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": early.id,
                        },
                        {
                            "id": "card_reveal",
                            "title": "Butler Reveal",
                            "node_ref": future.id,
                        },
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
                        },
                    ],
                },
            )
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ context_xml(plot_context(input.plot)) }}{% endrole %}',
            context={"input": {"plot": board.id}},
            env=env,
        )
        text = out.messages[0].blocks[0].text
        self.assertIn('completeness="whole_selection"', text)
        self.assertIn("Archive Break-in", text)
        self.assertIn("Butler Reveal", text)
        self.assertIn("claim_first_turn", text)
        self.assertIn("claim_resolution", text)
        self.assertNotIn("<placement", text)
        self.assertNotIn("<compression", text)
        self.assertNotIn("<ai_rubric", text)
        self.assertNotIn("<diagnostic_questions", text)
        self.assertNotIn("<failure_modes", text)
        self.assertNotIn("<claim_evidence_prompts", text)
        self.assertNotIn('{"', text)
        self.assertNotIn('"metadata"', text)

    def test_plot_context_accepts_template_instance_selection(self) -> None:
        archive = self.service.create_scene(CreateSceneRequest(title="Archive Break-in"))
        reveal = self.service.create_scene(CreateSceneRequest(title="Butler Reveal"))
        main_instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "first_turn", "notes": "Visible setup."}],
                },
            )
        )
        subplot_instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Subplot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "resolution", "notes": "Other line."}],
                },
            )
        )
        board = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={
                    "template_instance_ids": [main_instance.id, subplot_instance.id],
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "node_ref": archive.id,
                        },
                        {
                            "id": "card_reveal",
                            "title": "Butler Reveal",
                            "node_ref": reveal.id,
                        },
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": main_instance.id,
                            "plot_point_id": "first_turn",
                        },
                        {
                            "id": "claim_resolution",
                            "card_id": "card_reveal",
                            "template_instance_id": subplot_instance.id,
                            "plot_point_id": "resolution",
                        },
                    ],
                },
            )
        )
        self.assertEqual(board.entry_type, "plot:board")
        picked_instance = json.dumps(
            [
                {
                    "id": main_instance.id,
                    "kind": "plot",
                    "title": main_instance.title,
                    "entry_type": "plot:template_instance",
                }
            ]
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ context_xml(plot_context(input.plot)) }}{% endrole %}',
            context={"input": {"plot": picked_instance}},
            env=env,
        )

        text = out.messages[0].blocks[0].text
        self.assertIn(main_instance.title, text)
        self.assertIn("Visible setup.", text)
        self.assertIn("Archive Break-in", text)
        self.assertIn("claim_first_turn", text)
        self.assertNotIn(subplot_instance.title, text)
        self.assertNotIn("Other line.", text)
        self.assertNotIn("Butler Reveal", text)
        self.assertNotIn("claim_resolution", text)

    def test_plot_context_template_instance_selection_includes_unclaimed_points(self) -> None:
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Unclaimed main structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "enabled_point_ids": ["inciting_change", "first_turn"],
                    "point_notes": {
                        "inciting_change": {
                            "status": "planned",
                            "notes": "The invitation arrives.",
                        }
                    },
                },
            )
        )
        self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={"template_instance_ids": [instance.id]},
            )
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            '{% role "user" %}{{ context_xml(plot_context(input.plot)) }}{% endrole %}',
            context={"input": {"plot": instance.id}},
            env=env,
        )

        text = out.messages[0].blocks[0].text
        self.assertIn("Unclaimed main structure", text)
        self.assertIn("inciting_change", text)
        self.assertIn("The invitation arrives.", text)
        self.assertIn("first_turn", text)
        self.assertLess(text.index("inciting_change"), text.index("first_turn"))

    def test_plot_context_jinja_iteration_keeps_order_and_beat_fields(self) -> None:
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Selected main structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "enabled_point_ids": ["inciting_change", "first_turn"],
                },
            )
        )
        self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={"template_instance_ids": [instance.id]},
            )
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            """{% role "user" %}
{% set plot = plot_context(input.plot) %}
{% for instance in plot.template_instances %}
{% for point in instance.plot_points %}
{{ point.title }}|{{ point.function_claim }}|{{ point.guidance }}
{% endfor %}
{% endfor %}
{% endrole %}""",
            context={"input": {"plot": instance.id}},
            env=env,
        )

        text = out.messages[0].blocks[0].text
        self.assertLess(text.index("Inciting change"), text.index("First turn"))
        self.assertIn("Introduces a disruption", text)
        self.assertNotIn("Act I", text)
        self.assertNotIn("What changes because this function is present?", text)

    def test_plot_context_jinja_iteration_exposes_card_claims(self) -> None:
        main_instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "first_turn", "notes": "Visible setup."}],
                },
            )
        )
        subplot_instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Subplot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "resolution", "notes": "Other line."}],
                },
            )
        )
        self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={
                    "template_instance_ids": [main_instance.id, subplot_instance.id],
                    "plotlines": [
                        {
                            "id": "plotline_main",
                            "title": "Main plot",
                            "template_instance_id": main_instance.id,
                        },
                        {
                            "id": "plotline_sub",
                            "title": "Subplot",
                            "template_instance_id": subplot_instance.id,
                        },
                    ],
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                            "primary_plotline_id": "plotline_main",
                        }
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": main_instance.id,
                            "plot_point_id": "first_turn",
                            "plotline_id": "plotline_main",
                            "rationale": "The old path is unavailable.",
                        },
                        {
                            "id": "claim_resolution",
                            "card_id": "card_archive",
                            "template_instance_id": subplot_instance.id,
                            "plot_point_id": "resolution",
                            "plotline_id": "plotline_sub",
                            "rationale": "This belongs to the subplot.",
                        },
                    ],
                },
            )
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            """{% role "user" %}
{% set plot = plot_context(input.plot) %}
{% for card in plot.cards %}
CARD {{ card.title }} [{{ card.primary_plotline.title }}]: {{ card.synopsis }}
{% for claim in card.claims %}
CLAIM {{ claim.plot_point_id }} [{{ claim.plotline.title }}]: {{ claim.rationale }}
{% endfor %}
{% endfor %}
{% endrole %}""",
            context={"input": {"plot": main_instance.id}},
            env=env,
        )

        text = out.messages[0].blocks[0].text
        self.assertIn("CARD Archive Break-in [Main plot]: Mara steals the ledger.", text)
        self.assertIn(
            "CLAIM first_turn [Main plot]: The old path is unavailable.",
            text,
        )
        self.assertNotIn("resolution", text)
        self.assertNotIn("This belongs to the subplot.", text)

    def test_plot_brainstorm_default_prompt_renders_plot_context(self) -> None:
        target = self.service.create_scene(CreateSceneRequest(title="Quiet Aftermath"))
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [{"plot_point_id": "first_turn", "notes": "Visible setup."}],
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
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                            "node_ref": target.id,
                        }
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                        }
                    ],
                },
            )
        )
        prompt = self.service.read_prompt_entry("prompt_builtin_plot_brainstorm")
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
            prompt.body,
            context={
                "input": {
                    "plot": picked_board,
                    "focus": "Find pressure points.",
                },
                "scene": target,
            },
            env=env,
        )

        self.assertEqual([message.role for message in out.messages], ["system", "user"])
        system_text = out.messages[0].blocks[0].text
        user_text = out.messages[1].blocks[0].text
        self.assertIn("Do not draft the novel for the author", system_text)
        self.assertIn("Find pressure points.", user_text)
        self.assertIn('completeness="whole_selection"', user_text)
        self.assertIn("Book plot board", user_text)
        self.assertIn("Archive Break-in", user_text)
        self.assertIn("Visible setup.", user_text)
        self.assertNotIn("<ai_rubric", user_text)
        self.assertNotIn("<criterion>", user_text)
        self.assertNotIn('{"', user_text)

    def test_plot_claim_audit_default_prompt_renders_claim_context(self) -> None:
        template = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Three Act Template",
                entry_type="plot:template",
                body="Template notes.",
                template=PlotTemplateSpec(
                    slug="three-act",
                    display_name="Three Act",
                    family="act",
                    plot_points=[
                        {
                            "id": "first_turn",
                            "title": "First turn",
                            "function_claim": "Makes the old path unavailable.",
                        }
                    ],
                ),
            )
        )
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": template.id,
                    "title": "Main plot",
                    "plot_points": [
                        {
                            "plot_point_id": "first_turn",
                            "title": "First turn",
                            "function_claim": "Makes the old path unavailable.",
                            "notes": "Mara can no longer stay loyal to the archive.",
                        }
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
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                        },
                        {
                            "id": "card_friend",
                            "title": "Friend Warning",
                            "synopsis": "Jon warns Mara that the guild is watching.",
                        },
                    ],
                    "claims": [
                        {
                            "id": "claim_first_turn",
                            "card_id": "card_archive",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                            "claim_type": "satisfies",
                            "rationale": "The theft closes her old path.",
                            "evidence": "Mara steals the ledger.",
                        }
                    ],
                },
            )
        )
        prompt = self.service.read_prompt_entry("prompt_builtin_plot_claim_audit")
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
            prompt.body,
            context={
                "input": {
                    "plot": picked_board,
                    "focus": "Find weak claims.",
                }
            },
            env=env,
        )

        self.assertEqual([message.role for message in out.messages], ["system", "user"])
        system_text = out.messages[0].blocks[0].text
        user_text = out.messages[1].blocks[0].text
        self.assertIn("story marker", system_text)
        self.assertIn("Find weak claims.", user_text)
        self.assertIn("<plot_review", user_text)
        self.assertIn(f'<template_instance id="{instance.id}"', user_text)
        self.assertIn('<plot_beat id="first_turn"', user_text)
        self.assertIn("First turn", user_text)
        self.assertIn("claim_first_turn", user_text)
        self.assertIn('<card id="card_archive" title="Archive Break-in">', user_text)
        self.assertIn("Archive Break-in", user_text)
        self.assertIn("The theft closes her old path.", user_text)
        self.assertIn("<untagged_cards>", user_text)
        self.assertIn('<card id="card_friend" title="Friend Warning">', user_text)
        self.assertIn("Friend Warning", user_text)
        self.assertIn("<plot_suggestions>", user_text)
        self.assertIn("Do not emit placeholder suggestions", user_text)
        self.assertNotIn('{"', user_text)

    def test_jinja_iteration_exposes_point_claims(self) -> None:
        instance = self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Main plot structure",
                entry_type="plot:template_instance",
                template_instance={
                    "template_id": "plot_template_three_act",
                    "plot_points": [
                        {"plot_point_id": "first_turn", "notes": "Visible setup."}
                    ],
                },
            )
        )
        self.service.create_plot_node(
            CreatePlotNodeRequest(
                title="Book plot board",
                entry_type="plot:board",
                board={
                    "template_instance_ids": [instance.id],
                    "cards": [
                        {
                            "id": "card_archive",
                            "title": "Archive Break-in",
                            "synopsis": "Mara steals the ledger.",
                        },
                        {
                            "id": "card_friend",
                            "title": "Friend Warning",
                            "synopsis": "Jon warns Mara.",
                        },
                    ],
                    "claims": [
                        {
                            "id": "claim_archive",
                            "card_id": "card_archive",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                            "rationale": "The theft closes her old path.",
                        },
                        {
                            "id": "claim_friend",
                            "card_id": "card_friend",
                            "template_instance_id": instance.id,
                            "plot_point_id": "first_turn",
                            "claim_type": "partially_satisfies",
                            "rationale": "The warning raises pressure.",
                        },
                    ],
                },
            )
        )

        env = create_environment_for_project(self.service)
        out = render_template(
            """{% role "user" %}
{% set plot = plot_context(input.plot) %}
{% for instance in plot.template_instances %}
{% for point in instance.plot_points %}
POINT {{ point.title }}
{% for claim in point.claims %}
CLAIM {{ claim.card.title }}|{{ claim.claim_type }}|{{ claim.rationale }}
{% endfor %}
{% endfor %}
{% endfor %}
{% endrole %}""",
            context={"input": {"plot": instance.id}},
            env=env,
        )

        text = out.messages[0].blocks[0].text
        self.assertIn("POINT First turn", text)
        self.assertIn(
            "CLAIM Archive Break-in|satisfies|The theft closes her old path.",
            text,
        )
        self.assertIn(
            "CLAIM Friend Warning|partially_satisfies|The warning raises pressure.",
            text,
        )
