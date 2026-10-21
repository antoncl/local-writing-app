---
id: prompt_24dd1026e3
title: Summarize scene
entry_type: prompt:general
metadata:
  summary: "Writes a short synopsis of a scene from its prose, and revises it to the angle you ask for."
offer_on:
- manuscript:scene
inputs:
- name: entry
  type: context_pick
  label: Scene
  required: true
  target:
    sources:
    - kind: manuscript
      expr:
        type: manuscript:scene
    multiple: false
    presets: []
context_strategy:
  output:
    handler: extract_to_node
    commit:
      review: replace
---

{% set e = entry(inputs.entry) %}
{% role "system" %}
{# Register the one field this prompt writes (summary), so the commit saves
   exactly this set instead of re-deriving it. Emits nothing. #}
{% for f in fields(e) if f.proposable and f.id == "summary" %}{% do field_contract.store(f) %}{% endfor %}
{# `use(e)`, not `{{ e.body }}`: a chat renders this template once, at its
   first send, so printed prose would stay as it was then. `use()` sends the
   scene fresh on every turn, so the model sees the author's edits. #}
{% do use(e) %}
You are helping the author write a short synopsis of a scene — a few sentences that capture what happens and the job the scene does in the story. The scene is provided with this conversation: its prose body and its current summary, always as the author last saved them — if the author says they've changed the scene, work from the version you have now. Offer a synopsis directly; if the author asks for a different angle, length, or emphasis, revise it. Once the author is happy with it, they commit — you don't need to output anything structured yourself; a separate step extracts the synopsis from this conversation. The scene's prose body is the manuscript text and is never touched by this — only the summary field.
{% endrole %}
