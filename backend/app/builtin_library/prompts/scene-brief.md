---
id: prompt_f564c868ff
title: Scene brief
entry_type: prompt:snippet
metadata:
  summary: "The scene's brief — every field your schema gives a scene — for prompts that draft or check it."
---
{#
  Scene brief snippet (#2511): the scene as its author designed it — its summary,
  then every field the author filled in, each under its label and description,
  so a field the author adds to the scene's schema reaches the model without
  any prompt naming it. Include it inside a {% role %} block:
      {% include "Scene brief" %}

  Depends on: the scene the prompt is about. That is `prose_scene` when the
  including prompt sets it (a prompt working on a picked scene, as Draft scene
  does: `{% set prose_scene = e %}` before the include), else the render
  context's `scene` (the editor's scene, or the preview's target scene). With
  neither, it renders nothing. The same convention as "Character voice in
  prose" and "Prose generation settings" (#2634), so one `set` serves all three.
  A prompt written before #2634 may still set the retired `brief_scene`; it is
  read first, so such a prompt keeps briefing the scene it chose.

  Which fields: the ones the AI may write ("AI may write this field when
  committing a brainstorm" — `proposable`), plus references, which are story
  content too (characters, location). The rule Impersonate and the lore block
  use. Left out: `title` and `summary` (the heading and its first paragraph),
  `body` (the prose — the prompt decides whether to show it), `status` and
  `tags` (bookkeeping), and the narration fields `pov_mode` / `pov` / `tense`,
  which "Prose generation settings" and the prompt's point-of-view line carry.
  A select shows its option's label, not the stored value — in a list item
  too (#2515). A list field keeps its order, one numbered item per line (a
  grouped item as `Member: value` pairs, by member label).
  The line under the summary (#2604) says the brief is notes, not text: without
  it a model renders a purpose or value field by stating it in the prose.
#}
{#- A list item value by its option label, when its member has options. -#}
{% macro shown(member, value) %}{{ member.option_labels.get(value, value) if (member and value is string) else value }}{% endmacro %}
{% set s = brief_scene if brief_scene is defined else (prose_scene if prose_scene is defined else (scene if scene is defined else none)) %}
{% if s %}
## This scene: {{ s.title }}
{{ s.summary }}

_This brief is the author's notes on the scene, for you and not the reader: use it to decide what happens and how, but never quote, paraphrase or explain it in the prose. A note on what the scene is for is achieved by the scene happening, not by saying so._
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
{% set members = f.get("items") or [] %}
{% for item in v %}
{% if item is mapping %}
{{ loop.index }}. {% for k, iv in item.items() if iv %}{% set ms = members | selectattr("key", "equalto", k) | list %}{{ ms[0].label if ms else k }}: {{ shown(ms[0] if ms else none, iv) }}{{ "; " if not loop.last }}{% endfor %}

{% else %}
{{ loop.index }}. {{ shown(members[0] if members else none, item) }}
{% endif %}
{% endfor %}
{% else %}
{{ f.option_labels.get(v, v) }}
{% endif %}
{% endif %}
{% endif %}
{% endfor %}
{% endif %}
