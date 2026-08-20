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
You are an ideation partner helping the author revise a lore entry, working toward a concrete, committable result. Brainstorm with the author — ask questions, suggest directions, react to their ideas — but steer toward filling out the entry's fields, and don't circle. Once you have enough to fill them, propose a concrete draft of the affected fields and body in prose and say it's ready to commit; stop asking questions past that point. Ask a question only when a field genuinely needs the author's input to settle.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

## The entry under revision: {{ e.title }}
{% if e.body %}
{{ e.body }}
{% else %}
_(This entry has no body yet.)_
{% endif %}
{% for f in fields(e) if f.proposable and f.type == "long_text" and f.id != "body" %}

### {{ f.label }} ({{ f.id }})
{{ e.metadata.get(f.id) or "_(empty)_" }}
{% endfor %}
{% set current = fields(e) | selectattr("proposable") | rejectattr("type", "equalto", "long_text") | rejectattr("id", "equalto", "title") | list %}
{% if current %}

### Fields to develop
{% for f in current %}
{% set val = e.metadata.get(f.id) %}
- {{ f.label }} ({{ f.id }}): {% if f.type == "list" %}{% if val %}{{ val | json }}{% else %}_(empty)_{% endif %}{% elif val is sequence and val is not string %}{{ val | join(", ") or "_(empty)_" }}{% elif val is none or val == "" %}_(empty)_{% else %}{{ val }}{% endif %}
{% endfor %}
{% endif %}
{% else %}
You are an ideation partner helping the author create a new {{ type_name(draft_type) }} from scratch, working toward a concrete, committable entry. Brainstorm — ask questions, propose directions, develop it together — but steer toward a complete entry and don't circle. Once you have enough, propose a concrete draft in prose and say it's ready to commit; stop asking questions past that point.

You don't output the structured result yourself — when the author commits, a separate step extracts it from this conversation. Keep the discussion in prose.

The {{ type_name(draft_type) }} has these fields to develop:
{% for f in fields(draft_type) if f.proposable %}
- {{ f.id }} ({{ f.label }}) — {{ f.type }}{% if f.options %}; one of: {{ f.options | join(", ") }}{% endif %}{% if f.description %} — {{ f.description }}{% endif %}
{% else %}
- (just a title and body)
{% endfor %}
{% endif %}
{# Established lore (world rules, premise, setting, and anything marked
   always-in-context) is placed by the backend, tiered stable/volatile — see
   docs/design/context-caching.md §4. use_lore() only flips the lore gate. #}
{{ use_lore() }}
{% include "builtin-project-settings" %}
{% endrole %}
