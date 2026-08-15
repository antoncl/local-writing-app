---
id: builtin-project-settings
title: Project settings
entry_type: prompt:snippet
---
{#
  Project settings snippet (#1020 / finishes #317). Surfaces the project's
  authored settings — language, spelling, measurement system, tense, POV, … —
  so the model honours them. Include it INSIDE a {% role %} block:
      {% include "builtin-project-settings" %}
  Labels + display order come from field_catalog("project:project") (computed
  fields like Path and AI cost are already excluded); values from
  project.metadata. `color` is skipped and empty fields are omitted, so the
  block disappears entirely when nothing is set.
#}
{%- if project is defined and project and project.metadata -%}
{%- set ns = namespace(rows=[]) -%}
{%- for f in field_catalog("project:project") if f.id != "color" -%}
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
