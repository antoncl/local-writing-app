---
id: prompt_55f5c77e1b
title: Expand
entry_type: prompt:general
metadata:
  summary: "Rewrites the selected passage at greater length — as much longer as you choose — adding detail, interiority, and rhythm."
offer_on:
- manuscript:scene
inputs:
- name: amount
  type: select
  label: How much longer
  options:
  - value: '1.5'
    label: A little (about 1.5×)
  - value: '2'
    label: About double
  - value: '3'
    label: About triple
  default: '2'
- name: note
  type: long_text
  label: Direction (optional)
context_strategy:
  output:
    handler: inline
    destination: selection
---
{#
  Expand (#2565): rewrites the selected passage longer, in place. The length is
  a multiple of the passage's own word count, so "about double" means the same
  on a sentence and on a page. The passage is shown with the prose around it
  (the "Passage context" snippet) so the rewrite follows on from what comes
  before and leads into what comes after.

  The order is for caching (ADR-0084): the instructions, which rarely change,
  come first; the passage and its surroundings, which change every run, last.
#}
{%- set words = (selection.split() | length) if (selection is defined and selection) else 0 -%}
{%- set factor = (inputs.amount | float) if (inputs is defined and inputs.amount is defined and inputs.amount) else 2 -%}
{%- set target = (words * factor) | round | int -%}
{%- set target = ((target / 10) | round | int) * 10 if target >= 100 else target -%}
{% role "system" %}
Rewrite the passage the reader sends at greater length — deepen it with detail, interiority, and rhythm where they earn their place. Add texture, not filler; keep the story beats, the author's voice, and the tense, and don't add events the passage doesn't have. Your rewrite replaces the passage exactly where it stands: it follows on from the text before it and leads into the text after it, without repeating either. Return only the revised prose, with no preamble or explanation.

{% include "Prose generation settings" %}
{% include "Character voice in prose" %}
{% include "Project settings" %}
{% include "Relevant lore" %}
{% include "Author directions in brackets" %}
{% endrole %}
{% role "user" %}
{% include "Passage context" %}
## The passage
{% if target %}It is {{ words }} words; rewrite it at about {{ target }} words.

{% endif %}
{{ selection }}
{% if inputs is defined and inputs.note is defined and inputs.note %}

## Direction
{{ inputs.note }}
{% endif %}
{% endrole %}
