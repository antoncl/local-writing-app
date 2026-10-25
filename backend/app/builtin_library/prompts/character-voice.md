---
id: prompt_a954ecbc4c
title: Character voice in prose
entry_type: prompt:snippet
metadata:
  summary: "Use a character's signature words and tics sparingly, for prompts that write manuscript prose."
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
  carries. The scene is resolved as "Prose generation settings" does: the
  prompt's `prose_scene`, else the editor's `scene`, else none. A prompt that
  already places the character itself is deduped by id.
#}
{%- set pscene = prose_scene if prose_scene is defined else (scene if scene is defined else none) -%}
{%- set nar = resolved_narration(pscene) if pscene else none -%}
{%- if nar and nar.character %}{% do use(nar.character) %}{% endif %}
## Character voice
A character's notes describe how they tend to speak and act; they are not a quota. When the notes or the author's brief say how often a signature word, phrase or verbal habit should appear, follow that. Otherwise use each one at most once in what you write here, and only where it comes naturally — most passages need none. Carry a character's voice through the shape of their speech: register, sentence length, rhythm, what they leave unsaid.


