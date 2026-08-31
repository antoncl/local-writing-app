---
id: prompt_f784c122fa
title: Relevant lore
entry_type: prompt:snippet
inputs:
- name: lore
  type: context_pick
  label: Lore
  options: []
  required: false
  hidden: false
  target:
    sources:
    - kind: lore
      expr:
        union:
        - type: lore:character
        - type: lore:item
        - type: lore:location
        - type: lore:note
    presets: []
---
{#
  Adds an optional "Lore" picker to any prompt that includes it. Whatever the
  author picks is placed as context through the standard lore path (`use()` +
  `use_lore()` — the backend renders and caches it; nothing is printed inline).
  The picker is optional, so the snippet is INERT until something is picked:
  with no selection — or in a context that never even defines `inputs` — it
  changes the prompt not at all (the `is defined` guards hold under
  StrictUndefined; `and` short-circuits, so `inputs` is checked before
  `inputs.lore`). Include it INSIDE a {% role %} block of any prompt that could
  use extra story background:
      {% include "Relevant lore" %}
#}
{% if inputs is defined and inputs.lore is defined and inputs.lore %}{% do use(inputs.lore) %}{{ use_lore() }}{% endif %}
