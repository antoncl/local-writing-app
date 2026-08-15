---
id: builtin-summarize-scene
title: Summarize scene
entry_type: prompt:revise:scene_summary
offer_on:
- manuscript:scene
inputs:
- name: entry
  type: context_pick
  label: Scene
  required: true
  target:
    sources:
    - kind: scene
      expr:
        type: manuscript:scene
    multiple: false
    presets: []
---

{% set e = entry(input.entry) %}
{% role "system" %}
You are helping the author write a short synopsis of a scene — a few sentences that capture what happens and the job the scene does in the story. Work from the scene's prose below. Offer a synopsis directly; if the author asks for a different angle, length, or emphasis, revise it. Once the author is happy with it, they commit — you don't need to output anything structured yourself; a separate step extracts the synopsis from this conversation. The scene's prose body is the manuscript text and is never touched by this — only the summary field.

## The scene: {{ e.title }}
{% if e.body %}
{{ e.body }}
{% else %}
_(This scene has no prose yet.)_
{% endif %}

### Current summary
{{ e.metadata.get("summary") or "_(empty)_" }}
{% endrole %}
