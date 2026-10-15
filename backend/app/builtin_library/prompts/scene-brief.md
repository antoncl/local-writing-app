---
id: prompt_f564c868ff
title: Scene brief
entry_type: prompt:snippet
---
{#
  Scene brief snippet (#2511): the scene as its author designed it — its summary,
  then every field the author filled in, each under its label and description,
  so a field added to the scene's schema (a beat list, the value at stake, …)
  reaches the model without any prompt naming it. Set `brief_scene` to the scene
  node, then include it inside a {% role %} block:
      {% set brief_scene = e %}{% include "Scene brief" %}

  Which fields: the ones the AI may write ("AI may write this field when
  committing a brainstorm" — `proposable`), plus references, which are story
  content too (characters, location). The rule Impersonate and the lore block
  use. Left out: `title` and `summary` (the heading and its first paragraph),
  `body` (the prose — the prompt decides whether to show it), `status` and
  `tags` (bookkeeping), and the narration fields `pov_mode` / `pov` / `tense`,
  which "Prose generation settings" and the prompt's point-of-view line carry.
  A list field keeps its order, one numbered item per line.
#}
{% set s = brief_scene %}
## This scene: {{ s.title }}
{{ s.summary }}
{% for f in fields(s) if f.proposable or f.type in ("entity_ref", "entity_ref_list") %}
{% if f.id not in ("title", "summary", "body", "status", "tags", "pov_mode", "pov", "tense") %}
{% set v = field_value(s, f) %}
{% if v %}

### {{ f.label }}
{% if f.description %}
_{{ f.description }}_

{% endif %}
{% if f.type == "entity_ref" %}
{{ v.title }}
{% elif f.type == "entity_ref_list" %}
{{ v | map(attribute="title") | join(", ") }}
{% elif v is sequence and v is not string %}
{% for item in v %}
{{ loop.index }}. {{ (item.values() | map("string") | join(" — ")) if item is mapping else item }}
{% endfor %}
{% else %}
{{ v }}
{% endif %}
{% endif %}
{% endif %}
{% endfor %}
