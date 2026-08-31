---
id: prompt_7836e868f4
title: Shorten
entry_type: prompt:general
context_strategy:
  output:
    handler: inline
    destination: selection
---
{% role "system" %}
Rewrite the passage the reader sends to be shorter and tighter — cut padding, redundancy, and weak qualifiers. Keep every story beat, the author's voice, and the tense. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
