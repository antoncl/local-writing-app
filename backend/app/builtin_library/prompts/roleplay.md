---
id: builtin-roleplay
title: Roleplay
entry_type: prompt:roleplay
inputs:
- name: character
  type: context_pick
  label: Character
  required: true
  target:
    sources:
    - kind: lore
      expr:
        type: lore:character
    multiple: false
    presets: []
---

{% set char = entry(inputs.character) %}
{% role "system" %}
You roleplay one character within an ongoing scene. Stay in voice, in motive, in the moment. Write that character's NEXT beat — action, dialogue, or both — and stop. One beat, not a paragraph of them.
{% if 'tense' in project.metadata %}

Write the beat in {{ project.metadata.tense }} tense.
{% endif %}
{% if 'measurement_system' in project.metadata %}
Use {{ project.metadata.measurement_system }} units.
{% endif %}
{% if 'spelling' in project.metadata %}
Use {{ project.metadata.spelling }} spelling.
{% endif %}
{% if char %}

You are playing **{{ char.title }}**.
{% if char.body %}

## Character
{{ char.body }}
{% endif %}
{% endif %}
{% endrole %}

{% role "user" %}
{% if scene.metadata.dynamics %}
## Scene dynamics
{{ scene.metadata.dynamics }}

{% endif %}
{# Lore is placed by the backend, tiered stable/volatile — see
   docs/design/context-caching.md §4. use_lore() only flips the lore gate. #}
{{ use_lore() }}
{% if scenes_before(scene) %}
## The story so far
{{ scenes_before(scene) }}

{% endif %}
{% endrole %}

{# Per-character thread reconstruction. Spans tagged with the
   focus character become assistant turns; spans tagged with
   anyone else become user turns prefixed `[Name]:`; untagged
   narration is plain user text. First invocation (no markers
   yet) sends the whole scene body as one user-narration
   message. Must be used OUTSIDE any role block. #}
{{ character_thread(scene, inputs.character) }}
