---
id: builtin-prose-settings
title: Prose generation settings
entry_type: prompt:snippet
---
{#
  Prose-generation settings snippet (#1076). Surfaces the project's
  narrative-craft settings — POV + tense — that govern how manuscript PROSE
  reads. Include it INSIDE a {% role %} block, ONLY in prompts that generate
  manuscript prose:
      {% include "builtin-prose-settings" %}
  Kept OUT of metadata-field brainstorms (revise-entry) on purpose: a
  first-person, present-tense manuscript must not push a character's descriptive
  fields into first person. The general facts (language, spelling, units, …)
  live in `builtin-project-settings`. Values from project.metadata; empty
  settings are omitted, so the block disappears when nothing is set.
#}
{%- if project is defined and project and project.metadata -%}
{%- set ns = namespace(rows=[]) -%}
{%- for f in fields("project:project") if f.proposable and f.id in ["pov_mode", "tense"] -%}
{%- set val = project.metadata.get(f.id) -%}
{%- if val is not none and val != "" -%}{%- set ns.rows = ns.rows + [(f.label, val)] -%}{%- endif -%}
{%- endfor -%}
{%- if ns.rows %}
## Prose style
Write the manuscript prose in this narrative POV and tense.
{% for label, val in ns.rows -%}
- {{ label }}: {% if val is sequence and val is not string %}{{ val | join(", ") }}{% else %}{{ val }}{% endif %}
{% endfor -%}
{%- endif -%}
{%- endif -%}
