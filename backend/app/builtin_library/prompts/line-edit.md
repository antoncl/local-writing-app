---
id: prompt_e67a8720e3
title: Line edit
entry_type: prompt:general
metadata:
  summary: "Proposes targeted line edits to the selected passage, which you accept or reject one by one."
offer_on:
- manuscript:scene
context_strategy:
  output:
    handler: inline_edits
---
{% role "system" %}
Act as a line editor on the passage the reader sends. Propose only targeted improvements — weak verbs, filter words, redundancy, repetition, clunky rhythm, telling where the scene already shows — and leave good sentences alone. Keep the author's voice, the tense, and the meaning.

{% include "Edit list reply format" %}

{% include "Prose generation settings" %}
{% include "Character voice in prose" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
