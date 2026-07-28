"""Built-in prompt entries shipped as read-only project nodes."""

from __future__ import annotations

from typing import Any

PLOT_CONTEXT_INPUT: dict[str, Any] = {
    "name": "plot",
    "type": "context_pick",
    "label": "Plot context",
    "required": True,
    "target": {
        "sources": [
            {
                "kind": "plot",
                "expr": {
                    "union": [
                        {"type": "plot:board"},
                        {"type": "plot:template_instance"},
                    ]
                },
            }
        ],
        "multiple": False,
    },
}


def builtin_prompt_entries() -> list[dict[str, Any]]:
    return [
        {
            "filename": "Plot Brainstorm.md",
            "node_id": "prompt_builtin_plot_brainstorm",
            "title": "Plot Brainstorm",
            "entry_type": "prompt:general",
            "inputs": [
                PLOT_CONTEXT_INPUT,
                {
                    "name": "focus",
                    "type": "long_text",
                    "label": "Brainstorming focus",
                    "default": "Look for useful next questions, options, and pressure points.",
                },
            ],
            "body": PLOT_BRAINSTORM_BODY,
        },
        {
            "filename": "Plot Claim Audit.md",
            "node_id": "prompt_builtin_plot_claim_audit",
            "title": "Plot Claim Audit",
            "entry_type": "prompt:general",
            "inputs": [
                PLOT_CONTEXT_INPUT,
                {
                    "name": "focus",
                    "type": "long_text",
                    "label": "Audit focus",
                    "default": "Find weak, unsupported, duplicated, or missing plot-beat claims.",
                },
            ],
            "body": PLOT_CLAIM_AUDIT_BODY,
        },
    ]


PLOT_BRAINSTORM_BODY = """{% set selected_scene = scene if scene is defined else none %}
{% role "system" %}
You are an AI-assisted fiction-writing brainstorming partner for a novelist. Use the author's plot board and selected plot templates as a scaffold for thinking. Do not draft the novel for the author, invent final canon, or treat templates as mandatory rules. Offer concrete options, tradeoffs, questions, and pressure tests that help the author decide what to write.
{% endrole %}

{% role "user" %}
Use this plot board and its template guidance as the main brainstorming scaffold.

{% if input.focus is defined and input.focus %}
## Current focus
{{ input.focus }}

{% endif %}
## Plot board and templates
{{ context_xml(plot_context(input.plot)) }}

{% if selected_scene %}
## Current scene
Title: {{ selected_scene.title }}
{% set scene_summary = selected_scene.metadata.get("summary") if selected_scene.metadata is defined else "" %}
{% if scene_summary %}
Summary: {{ scene_summary }}
{% endif %}
{% endif %}

Respond with:
1. The strongest available story direction.
2. Two or three alternate directions worth considering.
3. Weak or unsupported plot-beat claims to investigate.
4. Specific questions the author should answer next.
{% endrole %}
"""


PLOT_CLAIM_AUDIT_BODY = """{% set selected_scene = scene if scene is defined else none %}
{% set plot = plot_context(input.plot, as_of=selected_scene) if selected_scene else plot_context(input.plot) %}
{% role "system" %}
You are an experienced fiction editor helping a novelist strengthen a plot board. A plot beat is a story milestone or required story function. A function badge is a card-local claim that the card helps satisfy that beat. Treat diagnostics as signals, not verdicts. Diagnose gaps, then offer concrete repair options the author can choose from. Do not draft prose, invent final canon, mutate the board, or treat the template as a rigid formula.
{% endrole %}

{% role "user" %}
{% if input.focus is defined and input.focus %}
## Audit focus
{{ input.focus }}

{% endif %}
<plot_claim_audit board_title="{{ plot.board_title | e }}">
{% for instance in plot.template_instances %}
  <template_instance id="{{ instance.id | e }}" title="{{ instance.title | e }}">
{% if instance.ai_use_guidance %}
    <ai_use_guidance>{{ instance.ai_use_guidance | e }}</ai_use_guidance>
{% endif %}
{% for point in instance.plot_points %}
    <plot_beat id="{{ point.plot_point_id | e }}" title="{{ point.title | e }}" status="{{ point.status | default('unplanned') | e }}">
      <function_claim>{{ point.function_claim | e }}</function_claim>
{% if point.notes %}
      <story_specifics>{{ point.notes | e }}</story_specifics>
{% endif %}
{% if point.author_intent %}
      <author_intent>{{ point.author_intent | e }}</author_intent>
{% endif %}
{% if point.expected_role %}
      <expected_role>{{ point.expected_role | e }}</expected_role>
{% endif %}
      <claiming_cards>
{% for claim in point.claims %}
        <claim id="{{ claim.id | e }}" type="{{ claim.claim_type | e }}" strength="{{ claim.strength | default('', true) | e }}">
{% if claim.card %}
          <card id="{{ claim.card.id | e }}" title="{{ claim.card.title | e }}">
{% if claim.card.synopsis %}
            <synopsis>{{ claim.card.synopsis | e }}</synopsis>
{% endif %}
          </card>
{% endif %}
{% if claim.claim_label %}
          <claim_label>{{ claim.claim_label | e }}</claim_label>
{% endif %}
{% if claim.rationale %}
          <rationale>{{ claim.rationale | e }}</rationale>
{% endif %}
{% if claim.evidence %}
          <evidence>{{ claim.evidence | e }}</evidence>
{% endif %}
{% if claim.ai_notes %}
          <ai_notes>{{ claim.ai_notes | e }}</ai_notes>
{% endif %}
        </claim>
{% endfor %}
      </claiming_cards>
    </plot_beat>
{% endfor %}
  </template_instance>
{% endfor %}
  <untagged_cards>
{% for card in plot.cards %}
{% if not card.claims %}
    <card id="{{ card.id | e }}" title="{{ card.title | e }}">
{% if card.synopsis %}<synopsis>{{ card.synopsis | e }}</synopsis>{% endif %}
    </card>
{% endif %}
{% endfor %}
  </untagged_cards>
</plot_claim_audit>

Respond with:
1. A brief diagnosis of the selected focus: what is strong, weak, unsupported, missing, duplicated, or overloaded.
2. Specific repair options: narrative actions, obstacles, choices, reveals, consequences, or relationship/status changes that would make the beat or card stronger.
3. Claim changes to consider: add, remove, move, split, downgrade, or strengthen function badges.
4. Evidence the author could add to the card or scene to make the claim feel earned.
5. Questions only where an author decision is genuinely needed.

Then include an optional machine-readable suggestion block. Use target ids from the context whenever possible. Keep every suggestion as a draft the author can accept, edit, or ignore. Do not emit placeholder suggestions. Omit the block entirely if there is no concrete proposed change.

<plot_suggestions>
  <suggestion kind="card_revision|beat_revision|claim_change|new_claim|relationship_change|scene_promotion|question" target_card_id="card_id_if_known" target_claim_id="claim_id_if_known" template_instance_id="template_instance_id_if_known" plot_point_id="plot_point_id_if_known">
    <title>Short label for a real suggestion</title>
    <reason>Why this concrete change would strengthen the story function.</reason>
    <proposed_change>Specific board-level edit or author decision, not drafted prose. For card_revision, write the replacement card synopsis.</proposed_change>
    <evidence_to_add>Concrete evidence the card or linked scene would need.</evidence_to_add>
    <story_specifics>For beat_revision only: the story-specific version of this generic plot beat.</story_specifics>
    <author_intent>For beat_revision only: what the author wants this beat to accomplish.</author_intent>
    <expected_role>For beat_revision only: the role this beat should play in this story.</expected_role>
    <open_question>For beat_revision only: one concrete unresolved author decision.</open_question>
    <status>unplanned|planned|drafted|satisfied|intentionally_omitted</status>
  </suggestion>
</plot_suggestions>
{% endrole %}
"""
