---
id: prompt_1f26e1b2dc
title: Prose generation settings
entry_type: prompt:snippet
metadata:
  summary: "The scene's point of view and tense, for prompts that write manuscript prose."
---
{#
  Prose-generation settings snippet (#1076; scene override #1321). Surfaces the
  narrative-craft settings — POV + tense — that govern how manuscript PROSE
  reads. Include it INSIDE a {% role %} block, ONLY in prompts that generate
  manuscript prose destined for a scene:
      {% include "Prose generation settings" %}
  Each setting is the scene's EFFECTIVE value (#2513): its own, else what it
  inherits down the manuscript (act, chapter, book — `resolved_narration`), else
  the project's. Shown by its option label. Kept OUT of
  chat / roleplay and metadata-field brainstorms (revise-entry) on purpose: a
  first-person, present-tense manuscript must not push a character's descriptive
  fields — or a chat reply — into first person. The general facts (language,
  spelling, units, …) live in `Project settings`. Empty settings are
  omitted, so the block disappears when nothing is set.
  The scene is the editor's current one; a prompt that works on a picked scene
  sets `prose_scene` to it first (#2604), so this block and the prompt's own
  viewpoint rule read the same narration. A scene's narration shows even when
  the project itself sets none.
#}
{%- set pscene = prose_scene if prose_scene is defined else (scene if scene is defined else none) -%}
{%- set nar = resolved_narration(pscene) if pscene else none -%}
{%- set pmeta = project.metadata if (project is defined and project and project.metadata) else {} -%}
{%- if nar or pmeta -%}
{%- set ns = namespace(rows=[]) -%}
{%- for f in fields("project:project") if f.proposable and f.id in ["pov_mode", "tense"] -%}
{%- set sval = ((nar.mode if f.id == "pov_mode" else nar.tense) if nar else none) -%}
{%- set val = sval or pmeta.get(f.id) -%}
{%- if val is not none and val != "" -%}{%- set ns.rows = ns.rows + [(f.label, f.option_labels.get(val, val))] -%}{%- endif -%}
{%- endfor -%}
{%- if ns.rows %}
## Prose style
Write the manuscript prose in this narrative POV and tense.
{% for label, val in ns.rows %}- {{ label }}: {{ (val | join(", ")) if (val is sequence and val is not string) else val }}
{% endfor %}

{% endif -%}
{%- endif -%}
