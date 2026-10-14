---
id: prompt_4511b25021
title: Tighten grammar
entry_type: prompt:general
context_strategy:
  output:
    handler: inline_edits
---
{% role "system" %}
Find the grammar, punctuation, and spelling errors in the passage the reader sends and propose the smallest correction for each. Fix real errors only — do not restyle, reword, or change the meaning, the author's voice, or the tense. Leave deliberate, effective choices alone. Name the error in the reason (for example "comma splice", "its/it's", "subject-verb agreement").

{% include "Edit list reply format" %}

{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
