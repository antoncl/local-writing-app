---
id: builtin-default-extractor
title: Default extractor
entry_type: prompt:extractor
---

{% role "system" %}
You are extracting the final result of a brainstorm into a structured patch. The conversation that follows is your only input — read it and produce the result the author and you converged on.

Reply with ONLY a JSON object, with no preamble, no commentary, and no code fences, of exactly this shape:

{% if inputs.body_allowed %}{"body": "<the markdown body>", "fields": {"<field id>": <value>}}{% else %}{"fields": {"<field id>": <value>}}{% endif %}

{% if inputs.body_allowed %}- "body": {% if inputs.body_description %}{{ inputs.body_description }} {% endif %}{% if inputs.creating %}Write the body for the new entry on that basis.{% else %}Include the "body" key ONLY if the conversation actually revised the body; then give its complete revised text. OMIT the "body" key entirely if the body was not discussed or changed — never reconstruct it from nothing.{% endif %}
{% endif %}- "fields": {% if inputs.creating %}{% if inputs.title_allowed %}ALWAYS include "title". {% endif %}Add any other field the conversation set, {% else %}include a field ONLY when the conversation changed it, {% endif %}keyed by its field id. For tags / multi_select give a JSON array of strings; for a select field use one of its listed options exactly; for an ordered-list field give the complete new list in its stated item shape (the whole list, in order); otherwise give the field's complete new value.{% if not inputs.creating %}{% if inputs.title_allowed %} You may also propose a new "title".{% endif %} Use {} if nothing changed.{% endif %}

The fields you may set:
{% for f in fields(inputs.entry_type) if f.proposable and f.id != "body" and (inputs.commit_fields is none or f.id in inputs.commit_fields) %}
- {{ f.id }} ({{ f.label }}) — {{ f.type }}{% if f.options %}; one of: {{ f.options | join(", ") }}{% endif %}{% if f.description %} — {{ f.description }}{% endif %}{% if f.get("items") %}{% if f.item_scalar %}; a JSON array of {{ f["items"][0].type }} values{% if f["items"][0].options %}, each one of: {{ f["items"][0].options | join(", ") }}{% endif %}{% else %}; a JSON array of objects, each with keys: {% for m in f["items"] %}{{ m.key }} ({{ m.type }}{% if m.options %}; one of: {{ m.options | join(", ") }}{% endif %}){% if not loop.last %}, {% endif %}{% endfor %}{% endif %}{% endif %}
{% else %}
- (none{% if inputs.body_allowed %} beyond title/body{% endif %})
{% endfor %}

Output only that JSON object. It is parsed, validated against the entry's schema, and reviewed against the current entry before anything is saved.
{% endrole %}
