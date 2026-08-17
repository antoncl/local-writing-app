---
id: builtin-project-settings
title: Project settings
entry_type: prompt:snippet
---
{#
  Project settings snippet (#1020 / finishes #317). Surfaces the project's
  GENERAL authored facts — language, spelling, measurement system, author,
  word-count target, series number — so the model honours them everywhere.
  Include it INSIDE a {% role %} block:
      {% include "builtin-project-settings" %}
  The narrative-craft settings (POV + tense) are deliberately NOT here — they
  live in `builtin-prose-settings` and belong only in manuscript-prose prompts,
  so a first-person project doesn't push metadata-field brainstorms into first
  person (#1076). Labels + display order come from fields("project:project"),
  kept to `f.proposable` so computed fields (Path, AI cost) stay excluded; values
  from project.metadata. `color`/`pov_mode`/`tense` are skipped and empty fields
  are omitted, so the block disappears entirely when nothing is set.
#}
{%- if project is defined and project and project.metadata -%}
{%- set ns = namespace(rows=[]) -%}
{%- for f in fields("project:project") if f.proposable and f.id not in ["color", "pov_mode", "tense"] -%}
{%- set val = project.metadata.get(f.id) -%}
{%- if val is not none and val != "" -%}{%- set ns.rows = ns.rows + [(f.label, val)] -%}{%- endif -%}
{%- endfor -%}
{%- if ns.rows %}
## Project settings
Honor these project-wide settings in everything you write.
{% for label, val in ns.rows -%}
- {{ label }}: {% if val is sequence and val is not string %}{{ val | join(", ") }}{% else %}{{ val }}{% endif %}
{% endfor -%}
{%- endif -%}
{%- endif -%}
