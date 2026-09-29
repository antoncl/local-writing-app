---
id: prompt_ca222add6c
title: Relevant manuscript and plot
entry_type: prompt:snippet
inputs:
- name: manuscript_plot
  type: context_pick
  label: Scenes & cards
  options: []
  required: false
  hidden: false
  target:
    sources:
    - kind: scene
      expr:
        type: manuscript:scene
    - kind: plot
      expr:
        descendants_of: plot:card
    presets: []
---
{#
  Adds an optional "Scenes & cards" picker to any prompt that includes it — the
  manuscript-and-plot sibling of "Relevant lore". Whatever the author picks is
  placed through the same path by `use()` (the backend renders and caches it;
  nothing is printed inline): a card arrives with its synopsis, a scene with its
  fields and its full prose — so pick scenes sparingly. A pick is the author's
  choice, so it is placed even when a spoiler-gated `plot_context` would hide
  that card. Inert until something is picked (the `is defined` guards hold under
  StrictUndefined). Include it INSIDE a {% role %} block of any prompt that has
  to stay in step with other parts of the story:
      {% include "Relevant manuscript and plot" %}
#}
{% if inputs is defined and inputs.manuscript_plot is defined and inputs.manuscript_plot %}{% do use(inputs.manuscript_plot) %}{% endif %}
