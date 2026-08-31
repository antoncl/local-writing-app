---
id: prompt_4655b40593
title: Show, don't tell
entry_type: prompt:general
context_strategy:
  output:
    handler: inline
    destination: selection
---
{% role "system" %}
Rewrite the passage the reader sends to dramatise what it currently states outright. Turn summary and named emotions into action, gesture, sensory detail, and dialogue that let the reader infer them. Keep the story beats, the author's voice, and the tense; don't invent new events. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
