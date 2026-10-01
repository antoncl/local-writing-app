---
id: prompt_b3f32b952a
title: Lore register
entry_type: prompt:snippet
---
{#
  Lore register snippet (#2371). How lore should READ, as opposed to how long it
  should be: the only guidance a model had before was length, and left to its
  defaults it writes lore as an essay — explaining, hedging, recapping — which
  slows the author down and spends the lore budget on padding.
  Include it INSIDE a {% role %} block, in prompts that write lore only:
      {% include "Lore register" %}
  It is a prompt rule, not the `body` field's description, on purpose: `body`
  is shared with plot cards, scenes and plotlines, whose bodies should stay
  full, and the rule has to reach every lore field, not only the body. A
  project can shadow this snippet with its own "Lore register" to tune it.
#}
Lore is reference material: the author scans it while writing, and the AI reads it as context. Write every field and the body like a series bible: each fact once, in the field where it belongs, stated plainly. Don't explain why a fact matters, don't hedge, don't recap, and don't add transitions that only connect. Prefer short declarative sentences; where the content is a list, write a list.
