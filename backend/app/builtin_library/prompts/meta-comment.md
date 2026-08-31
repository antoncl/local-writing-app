---
id: prompt_31e4fe7b6a
title: Author directions in brackets
entry_type: prompt:snippet
---
{#
  Teaches a revise prompt to treat [square-bracket] notes in the prose as
  directions to act on and then remove — not story text. Include it INSIDE a
  {% role %} block of any revise prompt:
      {% include "Author directions in brackets" %}
#}
Square brackets `[...]` in the passage are directions from the author to you, not part of the story. Follow the instruction inside them when you revise, then remove the brackets and their contents from your output — the reader must never see them.
Example: `[Describe the people on the street; where no details are given, invent them.]`
