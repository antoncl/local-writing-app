---
id: prompt_de9faf834c
title: Describe
entry_type: prompt:general
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
{% role "system" %}
Enrich the passage the reader sends with vivid, concrete sensory detail{% if inputs.senses is defined and inputs.senses %}, drawing especially on {{ inputs.senses | join(", ") }}{% endif %}. Ground the description in the moment; keep the story beats, the author's voice, and the tense, and don't change what happens. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Relevant lore" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
