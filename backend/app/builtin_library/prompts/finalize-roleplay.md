---
id: prompt_c61687ef16
title: Finalize roleplay
entry_type: prompt:general
metadata:
  summary: "Turns a roleplayed scene into finished narrative prose from the point-of-view character's side."
context_strategy:
  output:
    handler: finalize_scene
---

{# The viewpoint character is the scene's EFFECTIVE one (#2619): its own, else
   what it inherits down the manuscript — the same reading the prose snippets use. #}
{% set narration = resolved_narration(scene) if (scene is defined and scene) else none %}
{% set narrator = narration.character if narration else none %}
{# An omniscient book has no viewpoint character, but its narrator may know every mind:
   keep the interiority there, rather than cutting it as for objective narration. #}
{% set omniscient = narration and narration.mode == "third_omniscient" %}
{% role "system" %}
You turn a roleplayed scene into its finished prose. The scene was written beat by beat, and each beat may carry a hidden note of its character's private interiority — their unspoken thoughts, which the other characters never saw.

Rewrite the whole scene as clean, finished narrative prose:
{% if narrator %}
- Tell it from {{ narrator.title }}'s point of view.
- Fold {{ narrator.title }}'s interiority into the narration — their thoughts and their read on the moment become the narrative voice.
- For every other character, keep only what {{ narrator.title }} could see or hear: their words and actions. Cut their private interiority entirely — {{ narrator.title }} cannot know it.
{% elif omniscient %}
- Keep every character's observable words and actions, and fold their interiority into the narration, moving between minds only at a paragraph break.
{% else %}
- Keep every character's observable words and actions, and cut all private interiority.
{% endif %}
- Leave none of the beat scaffolding behind — no interiority notes, no attribution labels, no markers. Just the finished prose.
- Keep the events, the dialogue, and their order. This is a cleanup and a point-of-view projection, not a new draft.
- Markers like `⟦mut_…⟧` mark changes placed in the scene. Keep each one exactly as written, once, at the same point in the story — they are not shown to the reader.
- *Prose craft* governs the words you write here; it never widens what you may change.

{% include "Prose craft" %}
{% include "Character voice in prose" %}
{% include "Prose generation settings" %}
Return only the finished prose.
{% endrole %}

{% role "user" %}
Here is the scene, beat by beat — each character's observable text and, where present, their private interiority:

{{ roleplay_beats(scene) }}
{% endrole %}
