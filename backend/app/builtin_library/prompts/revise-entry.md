---
id: builtin-revise-entry
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
  required: false
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
{# Register the fields this prompt writes. The commit reads this same set back
   and writes exactly it — nothing more — so register the full proposable set
   (body included) to let the commit touch them all. The loop emits no text. #}
{% for f in fields(e) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
You are an ideation partner helping the author revise a lore entry, working toward a concrete, committable result. Brainstorm with the author — ask questions, suggest directions, react to their ideas — but steer toward filling out the entry's fields, and don't circle. Once you have enough to fill them, propose a concrete draft of the affected fields and body in prose and say it's ready to commit; stop asking questions past that point. Ask a question only when a field genuinely needs the author's input to settle.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

## The entry under revision: {{ e.title }}
{% if e.body %}
{{ e.body }}
{% else %}
_(This entry has no body yet.)_
{% endif %}

### Fields to develop
{# Show what the entry holds today, read straight from the fields registered
   above so this can never drift from what the commit writes. Body and title are
   shown above, so skip them here. #}
{% for f in field_contract.stored if f.id not in ["body", "title"] %}
- {{ f.label }} ({{ f.id }}): {{ field_value(e, f) }}
{% endfor %}
{% else %}
{# Register the fields this prompt writes — the full proposable set of the type
   being created. The commit reads this same set back and writes exactly it. #}
{% for f in fields(draft_type) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
You are an ideation partner helping the author create a new {{ type_name(draft_type) }} from scratch, working toward a concrete, committable entry. Brainstorm — ask questions, propose directions, develop it together — but steer toward a complete entry and don't circle. Once you have enough, propose a concrete draft in prose and say it's ready to commit; stop asking questions past that point.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

The {{ type_name(draft_type) }} has these fields to develop:
{# `field_contract.render` prints the registered fields as `- id (label) — type`
   lines — the same descriptor the commit uses, so the fields you show and the
   fields you write are one list. #}
{{ field_contract.render or "- (just a title and body)" }}
{% endif %}
{# Pull in established lore — world rules, premise, setting, and anything the
   author marked always-in-context. use_lore() just opens the gate; the app
   places the entries. #}
{{ use_lore() }}
{% include "builtin-project-settings" %}
{% endrole %}
