---
id: prompt_f564c868ff
title: Scene brief
entry_type: prompt:snippet
---
{#
  Scene brief snippet (#2511): the scene as its author designed it — its summary,
  then every field the author filled in, each under its label and description,
  so a field the author adds to the scene's schema reaches the model without
  any prompt naming it. Set `brief_scene` to the scene
  node, then include it inside a {% role %} block:
      {% set brief_scene = e %}{% include "Scene brief" %}

  Which fields: the ones the AI may write ("AI may write this field when
  committing a brainstorm" — `proposable`), plus references, which are story
  content too (characters, location). The rule Impersonate and the lore block
  use. Left out: `title` and `summary` (the heading and its first paragraph),
  `body` (the prose — the prompt decides whether to show it), `status` and
  `tags` (bookkeeping), and the narration fields `pov_mode` / `pov` / `tense`,
  which "Prose generation settings" and the prompt's point-of-view line carry.
  A select shows its option's label, not the stored value. A list field keeps
  its order, one numbered item per line (a grouped item as
  `member: value` pairs).
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
{% elif f.type == "multi_select" %}
{% for item in v %}{{ f.option_labels.get(item, item) }}{{ ", " if not loop.last }}{% endfor %}

{% elif v is sequence and v is not string %}
{% for item in v %}
{% if item is mapping %}
{{ loop.index }}. {% for k, iv in item.items() if iv %}{{ k }}: {{ iv }}{{ "; " if not loop.last }}{% endfor %}

{% else %}
{{ loop.index }}. {{ item }}
{% endif %}
{% endfor %}
{% else %}
{{ f.option_labels.get(v, v) }}
{% endif %}
{% endif %}
{% endif %}
{% endfor %}
