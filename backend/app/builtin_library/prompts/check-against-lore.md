---
id: prompt_5160b9ffbe
title: Check against lore
entry_type: prompt:general
offer_on:
- manuscript:scene
context_strategy:
  output:
    handler: inline_notes
---
{#
  Checks the selected passage against the story's lore (ADR-0098). It never
  rewrites: it answers with notes, each quoting a place in the passage and
  naming the lore entry it contradicts, and the writer decides what to do.

  The lore it checks is what the passage names: `lore_named_in(selection)` is
  the entries whose name or alias occurs in the passage, what those link to,
  and the scene's own links (its POV, location, ...). Anything picked in the
  "Relevant lore" picker is checked too. With nothing named and nothing picked
  there is nothing to check against, so the run stops and says so.
#}
{% set named = lore_named_in(selection) %}
{% do use(named) %}
{% if not named and not (inputs is defined and inputs.lore is defined and inputs.lore) %}
{{ stop("Nothing in the selection names a lore entry, and none was picked.") }}
{% endif %}
{% role "system" %}
Act as a continuity checker. Compare the passage the reader sends against the story's lore entries provided, and report only the places where the passage contradicts an entry. Never rewrite the passage and never suggest wording.

{% include "Notes reply format" %}

{% include "Relevant lore" %}
{% endrole %}
{% role "user" %}
{{ selection }}
{% endrole %}
