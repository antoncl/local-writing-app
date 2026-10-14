---
id: prompt_0670474a78
title: Continue
entry_type: prompt:general
inputs:
- name: length
  type: number
  label: Target length (words)
  default: 300
- name: note
  type: long_text
  label: Direction (optional)
context_strategy:
  output:
    handler: inline
---
{#
  Continue (#2457): pick the prose up at the cursor and keep writing — a
  passage, not the rest of the scene. The output is inserted at the cursor.

  The order is for caching (ADR-0084): what rarely changes comes first; the
  text around the cursor and the direction — which change on every run — come
  last.
#}
{% set before = prose(text_before) %}
{% set after = prose(text_after) %}
{% if not before.strip() %}
{{ stop("Continue picks up from the prose before the cursor — put the cursor after some text. To start an empty scene from its summary, use Draft scene.") }}
{% endif %}
{% set narration = resolved_narration(scene) if scene else none %}
{% role "system" %}
You continue a novel's prose from exactly where the author's cursor is. Pick up mid-flow: if the text breaks off mid-sentence, finish that sentence; otherwise start the next one. Match the voice, tense, and rhythm of what is already written.

- Write a passage, not the rest of the scene. Stop at a natural pause near the target length; do not wrap the scene up, and do not end on a reflective or summarizing paragraph.
- Do not repeat or paraphrase the text before the cursor.
- When there is text after the cursor, what you write must lead into it without contradicting it.
- Do not invent major events, and do not bring in named characters the context does not give you.
- Return only the new prose: no title, no headings, no Markdown, no preamble or comment.

{% include "Prose generation settings" %}
{% if narration and narration.character %}
The point-of-view character is **{{ narration.character.title }}**.

{% endif %}
{% include "Project settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{% if narration and narration.character %}{% do use(narration.character) %}{% endif %}
{% include "Relevant lore" %}
{{ auto_lore() }}
{% if scene %}
{% if story_so_far(scene) %}
## The story so far
{{ story_so_far(scene) }}

{% endif %}
{% if scene.summary %}
## This scene: {{ scene.title }}
{{ scene.summary }}

{% endif %}
{% if scene.metadata.dynamics %}
### Scene dynamics
{{ scene.metadata.dynamics }}

{% endif %}
{% endif %}
## The text so far
Continue from the end of this.

{{ last_words(before, 800) }}
{% if after.strip() %}

## The text after the cursor
Your passage goes before this, and must lead into it. Do not write any of it.

{{ after }}
{% endif %}
{% if inputs.note is defined and inputs.note %}

## Direction
{{ inputs.note }}
{% endif %}

Continue the prose, about {{ inputs.length | default(300) }} words.
{% endrole %}
