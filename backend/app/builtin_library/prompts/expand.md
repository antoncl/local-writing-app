---
id: builtin-expand
title: Expand
entry_type: prompt:general
context_strategy:
  output:
    handler: inline
    destination: selection
---
{% role "system" %}
Rewrite the passage the reader sends at greater length — deepen it with detail, interiority, and rhythm where they earn their place. Add texture, not filler; keep the story beats, the author's voice, and the tense. Return only the revised prose, with no preamble or explanation.

{% include "builtin-prose-settings" %}
{% include "builtin-meta-comment" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
