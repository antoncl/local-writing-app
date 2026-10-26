---
id: prompt_a954ecbc4c
title: Character voice in prose
entry_type: prompt:snippet
metadata:
  summary: "A character's narrating and speaking voice, and their signature words used sparingly, for prompts that write manuscript prose."
---
{#
  Character voice snippet (#2580). A character's notes often list signature
  words, phrases or verbal habits; a model reads that list as a checklist and
  puts the tics in nearly every paragraph. This tells it they are tendencies:
  the author's own stated frequency wins, otherwise at most once per passage,
  and the voice is carried by the shape of the speech instead.
  Include it INSIDE a {% role %} block, after "Prose craft" and before
  "Prose generation settings", in prompts that write manuscript prose:
      {% include "Character voice in prose" %}
  Unlike the settings snippet the rule is unconditional: it holds whatever the
  project has set.

  It also places the viewpoint character's entry (#2619, ADR-0101 decision 3),
  so all ten prose built-ins send the character whose voice the narration
  carries. A prompt that already places the character itself is deduped by id.

  Depends on: the scene the prompt is about. That is `prose_scene` when the
  including prompt sets it (`{% set prose_scene = e %}` before the include),
  else the render context's `scene` (the editor's scene, or the preview's target
  scene); with neither, no character is placed. The same convention as "Prose
  generation settings" and "Scene brief" (#2634).

  A voice has two parts (#2625, ADR-0101 decision 6): the narrating voice holds
  only while that character is the viewpoint, the speaking voice whenever they
  speak. A sample shows the narrating voice; "write like it, never from it"
  answers the baseline, where drafts lifted 7-12-word runs from samples.
#}
{%- set pscene = prose_scene if prose_scene is defined else (scene if scene is defined else none) -%}
{%- set nar = resolved_narration(pscene) if pscene else none -%}
{%- if nar and nar.character %}{% do use(nar.character) %}{% endif %}
## Character voice
A character's entry may describe their voice in two parts, and each applies at its own time:
- **The narrating voice** applies only while that character is the viewpoint. It covers what they notice first and never notice, what they compare things to, how they name what they see, how deep the interiority runs and how a thought surfaces, and how the body registers. It shapes the narration, not only their lines, and it is theirs alone: when someone else is the viewpoint, the narration doesn't take on this character's way of seeing, even in a scene they're in.
- **The speaking voice** applies whenever they speak, viewpoint or not: register, sentence length, rhythm, and what they leave unsaid.
- **A sample passage,** when the entry has one, shows the narrating voice at work. Write like it, never from it: don't reuse its sentences, images or events.

An entry that doesn't separate the two parts: read its notes as both, and keep the narration in the viewpoint character's way of seeing. A voice changes how things are said, never how they are set on the page: the style note's mechanics hold whoever narrates.

A character's notes describe how they tend to speak and act; they are not a quota. When the notes or the author's brief say how often a signature word, phrase or verbal habit should appear, follow that. Otherwise use each one at most once in what you write here, and only where it comes naturally — most passages need none. Carry a character's voice through the shape of their speech: register, sentence length, rhythm, what they leave unsaid.


