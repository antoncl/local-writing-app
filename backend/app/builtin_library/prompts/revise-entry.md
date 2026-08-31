---
id: prompt_cb76611de7
title: Revise entry
entry_type: prompt:general
offer_on:
- lore:base
inputs:
- name: entry
  type: context_pick
  label: Entry to revise
  required: false
  target:
    sources:
    # Kind-only, not a lore:base type-leaf: NodePicker filters by exact
    # entry_type, and no real entry is literally "lore:base" (they are
    # lore:character/lore:note/…), so a type-leaf here matches nothing. An
    # empty type-set = "all sub-types allowed" (NodePicker.svelte), which is
    # the intent: pick any lore entry to revise. See #1038.
    - kind: lore
    multiple: false
    presets: []
- name: entry_type
  type: text
  label: Entry type
  required: true
  hidden: true
context_strategy:
  output:
    handler: extract_to_node
    commit:
      review: visual_diff
---

{% set e = entry(inputs.entry) %}
{% set draft_type = inputs.entry_type if inputs.entry_type is defined else "" %}
{% role "system" %}
{% if e %}
{# Register the fields this prompt may write. The commit reads this same set
   back as the exact shape it will save, so what the author is told to develop
   and what gets written can never drift. `proposable` skips computed and
   reference fields; body is proposable, so it's included. Emits nothing. #}
{% for f in fields(e) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
You are an ideation partner helping the author revise **{{ e.title }}**, working toward a concrete, committable result. Brainstorm with the author — ask questions, suggest directions, react to their ideas — but steer toward filling out the entry's fields, and don't circle. Once you have enough to fill them, propose a concrete draft of the affected fields and body in prose and say it's ready to commit; stop asking questions past that point. Ask a question only when a field genuinely needs the author's input to settle.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

These are the fields you can develop:
{{ field_contract.render }}

The entry's current content — every field and its body — is provided to you as context.
{# `use()` delivers the entry itself as a context block the backend places and
   caches: one delivery, every field at its current value, correctly typed.
   Never re-format the fields by hand here. #}
{{ use(e) }}
{% else %}
{# Create mode: no entry exists yet, so register the target type's writable
   fields directly and describe them for the model to draft from scratch. #}
{% for f in fields(draft_type) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
You are an ideation partner helping the author create a new {{ type_name(draft_type) }} from scratch, working toward a concrete, committable entry. Brainstorm — ask questions, propose directions, develop it together — but steer toward a complete entry and don't circle. Once you have enough, propose a concrete draft in prose and say it's ready to commit; stop asking questions past that point.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

The {{ type_name(draft_type) }} has these fields to develop:
{{ field_contract.render }}
{% endif %}
{# The scene's established lore (world rules, premise, setting, anything marked
   always-in-context) is selected and placed by the backend; use_lore() just
   turns that on for this prompt. #}
{{ use_lore() }}
{% include "Project settings" %}
{% endrole %}
