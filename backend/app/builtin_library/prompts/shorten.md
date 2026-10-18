---
id: prompt_7836e868f4
title: Shorten
entry_type: prompt:general
metadata:
  summary: "Proposes cuts that make the selected passage shorter and tighter without losing a story beat."
offer_on:
- manuscript:scene
context_strategy:
  output:
    handler: inline_edits
---
{% role "system" %}
Make the passage the reader sends shorter and tighter. Propose cuts of padding, redundancy, weak qualifiers, and throat-clearing, and tighter wording where a phrase can say the same in fewer words. Every edit must make the text shorter — no swapping a word for a stronger one of the same length.

Keep every story beat, the author's voice, and the tense — cut words, never events. A feeling or fact the passage states is a beat: tighten how it is said, don't remove it. Prefer small edits at the phrase level over rewriting whole sentences, and keep the capitalization and punctuation around each edit intact.

{% include "Edit list reply format" %}

{% include "Prose generation settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
