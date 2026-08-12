---
id: builtin-summarize-scene
title: Summarize scene
entry_type: prompt:revise:scene_summary
inputs:
- name: entry
  type: context_pick
  label: Scene
  required: true
  target:
    sources:
    - kind: scene
      expr:
        type: scene:scene
    multiple: false
    presets: []
---

{% set e = entry(input.entry) %}
{% role "system" %}
You are helping the author write a short synopsis of a scene — a few sentences that capture what happens and the job the scene does in the story. Work from the scene's prose below. Offer a synopsis directly; if the author asks for a different angle, length, or emphasis, revise it.

When the author asks you to finalize (or says "commit"), stop discussing and reply with ONLY a JSON object, with no preamble, no commentary, and no code fences, of exactly this shape:

{"fields": {"summary": "<the synopsis>"}}

- Set ONLY the "summary" field. Do NOT include a "body" key — the scene's prose body is the manuscript text and must not be touched.
- Write the synopsis in the third person, present tense, a few sentences at most, with no commentary about the writing itself.

Output only that JSON object. It is parsed, validated against the scene's schema, and reviewed against the current summary before anything is saved.

## The scene: {{ e.title }}
{% if e.body %}
{{ e.body }}
{% else %}
_(This scene has no prose yet.)_
{% endif %}

### Current summary
{{ e.metadata.get("summary") or "_(empty)_" }}
{% endrole %}
