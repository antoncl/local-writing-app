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
        - descendants_of: lore:character
        - descendants_of: lore:item
        - descendants_of: lore:location
        - descendants_of: lore:note
    presets: []
---
{#
  Adds an optional "Lore" picker to any prompt that includes it. Whatever the
  author picks here is the writer's explicit extra picks and nothing more —
  placed through the standard lore path by `use()` (the backend renders and
  caches it; nothing is printed inline). It does NOT turn automatic lore on:
  a prompt that wants that calls `use_lore()` itself (ADR-0092 §7.1). The
  picker is optional, so the snippet is INERT until something is picked: with
  no selection — or in a context that never even defines `inputs` — it changes
  the prompt not at all (the `is defined` guards hold under StrictUndefined;
  `and` short-circuits, so `inputs` is checked before `inputs.lore`). Include
  it INSIDE a {% role %} block of any prompt that could use extra story
  background:
      {% include "Relevant lore" %}
#}
{% if inputs is defined and inputs.lore is defined and inputs.lore %}{% do use(inputs.lore) %}{% endif %}
