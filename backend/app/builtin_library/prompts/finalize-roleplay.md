---
id: builtin-finalize-roleplay
title: Finalize roleplay
entry_type: prompt:general
context_strategy:
  output:
    handler: finalize_scene
---

{% set narrator = pov(scene) %}
{% role "system" %}
You turn a roleplayed scene into its finished prose. The scene was written beat by beat, and each beat may carry a hidden note of its character's private interiority — their unspoken thoughts, which the other characters never saw.

Rewrite the whole scene as clean, finished narrative prose:
{% if narrator %}
- Tell it from {{ narrator.title }}'s point of view.
- Fold {{ narrator.title }}'s interiority into the narration — their thoughts and their read on the moment become the narrative voice.
- For every other character, keep only what {{ narrator.title }} could see or hear: their words and actions. Cut their private interiority entirely — {{ narrator.title }} cannot know it.
{% else %}
- Keep every character's observable words and actions, and cut all private interiority.
{% endif %}
- Leave none of the beat scaffolding behind — no interiority notes, no attribution labels, no markers. Just the finished prose.
- Keep the events, the dialogue, and their order. This is a cleanup and a point-of-view projection, not a new draft.
{% if 'tense' in project.metadata %}
- Write in {{ project.metadata.tense }} tense.
{% endif %}

Return only the finished prose.
{% endrole %}

{% role "user" %}
Here is the scene, beat by beat — each character's observable text and, where present, their private interiority:

{{ roleplay_beats(scene) }}
{% endrole %}
