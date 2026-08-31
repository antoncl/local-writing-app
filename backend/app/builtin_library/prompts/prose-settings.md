---
id: prompt_1f26e1b2dc
title: Prose generation settings
entry_type: prompt:snippet
---
{#
  Prose-generation settings snippet (#1076; scene override #1321). Surfaces the
  narrative-craft settings — POV + tense — that govern how manuscript PROSE
  reads. Include it INSIDE a {% role %} block, ONLY in prompts that generate
  manuscript prose destined for a scene:
      {% include "Prose generation settings" %}
  Each setting resolves scene-first: a scene's own pov_mode / tense wins, and
  falls back to the project's when the scene leaves it blank. Kept OUT of
  chat / roleplay and metadata-field brainstorms (revise-entry) on purpose: a
  first-person, present-tense manuscript must not push a character's descriptive
  fields — or a chat reply — into first person. The general facts (language,
  spelling, units, …) live in `Project settings`. Empty settings are
  omitted, so the block disappears when nothing is set.
#}
{%- if project is defined and project and project.metadata -%}
{%- set ns = namespace(rows=[]) -%}
{%- for f in fields("project:project") if f.proposable and f.id in ["pov_mode", "tense"] -%}
{%- set sval = (scene.metadata.get(f.id) if (scene is defined and scene) else none) -%}
{%- set val = sval or project.metadata.get(f.id) -%}
{%- if val is not none and val != "" -%}{%- set ns.rows = ns.rows + [(f.label, val)] -%}{%- endif -%}
{%- endfor -%}
{%- if ns.rows %}
## Prose style
Write the manuscript prose in this narrative POV and tense.
{% for label, val in ns.rows %}- {{ label }}: {{ (val | join(", ")) if (val is sequence and val is not string) else val }}
{% endfor %}

{% endif -%}
{%- endif -%}
