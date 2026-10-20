---
id: prompt_f20764970b
title: Passage context
entry_type: prompt:snippet
metadata:
  summary: "The prose around a selected passage and the lore it names, for prompts that rewrite the passage in place."
---
{#
  Passage context snippet (#2565): what a prompt that REWRITES the selection in
  place (Expand, Describe, Rephrase) needs around it, so the rewrite keeps the
  voice and meets the text at both seams:
    - the prose on either side of the selection, marked as context only;
    - the lore the passage names, and the scene's point-of-view character,
      placed as they stand where the selection starts — so a change later in
      the scene doesn't leak into the rewrite.
  Include it INSIDE the {% role "user" %} block, before the passage:
      {% include "Passage context" %}
  The editor sends about 400 words on each side of a selection. Every piece is
  guarded, so outside the editor (no text around it, no scene) the snippet
  adds nothing.
#}
{%- if scene is defined and scene -%}
{%- do lore_as_of("selection") -%}
{%- set narration = resolved_narration(scene) -%}
{%- if narration.character %}{% do use(narration.character) %}{% endif -%}
{%- endif -%}
{%- if selection is defined and selection %}{% do use(lore_named_in(selection)) %}{% endif -%}
{%- set before = prose(text_before) if (text_before is defined and text_before) else "" -%}
{%- set after = prose(text_after) if (text_after is defined and text_after) else "" -%}
{% if before.strip() %}
## The text before the passage
Context only; do not rewrite it. The passage follows straight on from its last words.

{{ last_words(before, 400) }}

{% endif %}
{% if after.strip() %}
## The text after the passage
Context only; do not rewrite it. The passage must lead into it.

{{ after.strip() }}

{% endif %}
