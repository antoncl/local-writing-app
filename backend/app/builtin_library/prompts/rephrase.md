---
id: prompt_d026628591
title: Rephrase
entry_type: prompt:general
metadata:
  summary: "Rewrites the selected passage in fresh words, keeping its meaning, voice, and tense."
offer_on:
- manuscript:scene
context_strategy:
  output:
    handler: inline
    destination: selection
---
{#
  Rephrase (#2565): rewrites the selected passage in fresh words, in place. The
  passage is shown with the prose around it (the "Passage context" snippet) so
  the new wording keeps the voice and meets the text at both ends.
#}
{% role "system" %}
Rewrite the passage the reader sends in fresh words — vary the sentence shapes and diction while keeping the same meaning, the same story beats, the author's voice, and the tense. Offer a genuine alternative, not a light reshuffle. Your rewrite replaces the passage exactly where it stands: it follows on from the text before it and leads into the text after it, without repeating either. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Character voice in prose" %}
{% include "Project settings" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{% include "Passage context" %}
## The passage

{{ selection }}
{% endrole %}
