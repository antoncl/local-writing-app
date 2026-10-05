---
id: prompt_7c1e4a92d6
title: Draft scene
entry_type: prompt:general
inputs:
- name: length
  type: number
  label: Target length (words)
  default: 1200
- name: include_previous_scene
  type: boolean
  label: Continue from the previous scene's prose
  default: true
- name: note
  type: long_text
  label: Direction for this draft
context_strategy:
  output:
    handler: inline
---
{#
  Draft scene (#2421): the first draft of a scene, written from its summary.
  Run it in an empty scene — the draft is inserted at the cursor, so nothing
  already in the body (including mutation anchors) is replaced.

  The order is for caching (ADR-0084): what rarely changes comes first, the
  brief for this one scene comes last.
#}
{% if not scene %}
{{ stop("Draft scene needs a scene — run it from a scene in the manuscript.") }}
{% elif not scene.summary %}
{{ stop("This scene has no summary yet. Write one — what happens, who is in it, how it ends — and run Draft scene again.") }}
{% endif %}
{% set narration = resolved_narration(scene) %}
{% set previous = previous_scene(scene) %}
{% set following = next_scene(scene) %}
{% set changes = scene_mutations(scene) %}
{% do lore_as_of("start") %}
{% role "system" %}
You write the first draft of one scene of a novel, from the author's summary of it. A first draft gets the scene onto the page: every event in the summary, in order, dramatized as it happens — action, dialogue, and the point-of-view character's perception — not reported after the fact. It does not need to be polished.

- Write only this scene. Stop when its last event has happened; do not carry on into what comes next, and do not end on a reflective or summarizing paragraph.
- Do not invent major events the summary does not call for, and do not bring in named characters the context does not give you.
- Keep dialogue tags plain.
- Return only the prose of the scene: no title, no headings, no Markdown, no preamble or comment — apart from the change markers, when the brief lists any.

{% include "Prose generation settings" %}
{% if narration.character %}
The point-of-view character is **{{ narration.character.title }}**.

{% endif %}
{% include "Project settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{% if narration.character %}{% do use(narration.character) %}{% endif %}
{% for c in changes if c.entity %}{% do use(c.entity) %}{% endfor %}
{% include "Relevant lore" %}
{% if story_so_far(scene) %}
## The story so far
{{ story_so_far(scene) }}

{% endif %}
{% if inputs.include_previous_scene | default(true) and previous and previous.body %}
## Where the previous scene left off
The last lines of the previous scene, as written. Pick up from here, and match its voice.

{{ last_words(previous.body, 300) }}

{% endif %}
{% if following and following.summary %}
## The next scene
What happens next, so this scene can lead into it. Do not write any of it.

{{ following.summary }}

{% endif %}
## This scene: {{ scene.title }}
{{ scene.summary }}
{% if scene.metadata.dynamics %}

### Scene dynamics
{{ scene.metadata.dynamics }}
{% endif %}
{% if changes %}

### Changes this scene makes
These happen during the scene, in this order. Make each one happen in the story, and at the moment it happens write its marker exactly as shown — on its own, nothing else inside the brackets. The reader never sees the markers.
{% for c in changes %}- `⟦{{ c.anchor_id }}⟧` {{ c.text }}
{% endfor %}
{% endif %}
{% if inputs.note is defined and inputs.note %}

### Direction for this draft
{{ inputs.note }}
{% endif %}

Write the scene, about {{ inputs.length | default(1200) }} words.
{% endrole %}
