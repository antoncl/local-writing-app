---
id: prompt_de9faf834c
title: Describe
entry_type: prompt:general
metadata:
  summary: "Rewrites the selected passage as a vivid description, drawing on the senses you choose."
offer_on:
- manuscript:scene
inputs:
- name: senses
  type: multi_select
  label: Senses
  options:
  - value: sight
    label: Sight
  - value: sound
    label: Sound
  - value: smell
    label: Smell
  - value: taste
    label: Taste
  - value: touch
    label: Touch
context_strategy:
  output:
    handler: inline
    destination: selection
---
{#
  Describe (#2565): rewrites the selected passage with concrete sensory detail,
  in place. The passage is shown with the prose around it (the "Passage
  context" snippet) so the description fits the moment it sits in.
#}
{% role "system" %}
Enrich the passage the reader sends with vivid, concrete sensory detail{% if inputs is defined and inputs.senses is defined and inputs.senses %}, drawing especially on {{ inputs.senses | join(", ") }}{% endif %}. Ground the description in the moment; keep the story beats, the author's voice, and the tense, and don't change what happens. Your rewrite replaces the passage exactly where it stands: it follows on from the text before it and leads into the text after it, without repeating either. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Character voice in prose" %}
{% include "Project settings" %}
{% include "Relevant lore" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{% include "Passage context" %}
## The passage

{{ selection }}
{% endrole %}
