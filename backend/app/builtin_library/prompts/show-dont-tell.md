---
id: prompt_4655b40593
title: Show, don't tell
entry_type: prompt:general
metadata:
  summary: "Finds places where the passage states what it could dramatise and proposes scenes that show it."
offer_on:
- manuscript:scene
context_strategy:
  output:
    handler: inline_edits
---
{% role "system" %}
Find the places where the passage the reader sends states outright what it could dramatise — summary, and named emotions like "she was afraid". For each, propose a replacement that shows it instead through action, gesture, sensory detail, or dialogue, so the reader infers it — never just cut the telling, the replacement must carry what it said. Name what was told in the reason. Keep the story beats, the author's voice, and the tense; don't invent new events, and leave telling that is a deliberate, effective choice alone.

{% include "Edit list reply format" %}

{% include "Prose generation settings" %}
{% include "Character voice in prose" %}
{% include "Relevant lore" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
