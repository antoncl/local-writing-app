---
id: builtin-rephrase
title: Rephrase
entry_type: prompt:general
context_strategy:
  output:
    handler: inline
    destination: selection
---
{% role "system" %}
Rewrite the passage the reader sends in fresh words — vary the sentence shapes and diction while keeping the same meaning, the same story beats, the author's voice, and the tense. Offer a genuine alternative, not a light reshuffle. Return only the revised prose, with no preamble or explanation.

{% include "builtin-meta-comment" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
