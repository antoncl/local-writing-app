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
  Include it INSIDE a {% role %} block, next to "Prose generation settings",
  in prompts that write manuscript prose:
      {% include "Character voice in prose" %}
  Unlike that snippet it is unconditional: the rule holds whatever the project
  has set.
#}
## Character voice
A character's notes describe how they tend to speak and act; they are not a quota. When the notes or the author's brief say how often a signature word, phrase or verbal habit should appear, follow that. Otherwise use each one at most once in what you write here, and only where it comes naturally — most passages need none. Carry a character's voice through the shape of their speech: register, sentence length, rhythm, what they leave unsaid.

