---
id: builtin-tighten-grammar
title: Tighten grammar
entry_type: prompt:general
context_strategy:
  output:
    handler: inline
    destination: selection
---
{% role "system" %}
Correct the grammar, punctuation, and spelling in the passage the reader sends. Make the smallest changes that fix real errors — do not restyle, reword, or change the meaning, the author's voice, or the tense. Leave deliberate, effective choices alone. Return only the corrected prose, with no preamble or explanation.

{% include "builtin-meta-comment" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
