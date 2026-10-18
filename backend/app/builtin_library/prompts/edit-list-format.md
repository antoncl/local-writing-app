---
id: prompt_c48d8aa36f
title: Edit list reply format
entry_type: prompt:snippet
metadata:
  summary: "Tells a prompt to answer with small reasoned edits you accept or reject one by one."
---
{#
  The reply contract of an edit-list revise prompt (#2460, #2474): a prompt
  whose output handler is `inline_edits` answers with small reasoned edits the
  writer accepts or rejects one by one, not with replacement prose. Include it
  INSIDE the system {% role %} block of any such prompt, after the prompt's own
  instructions (what to look for):
      {% include "Edit list reply format" %}
  The app places an edit only when its `find` occurs exactly once in the
  selection, so the rules below are what make an edit land.
#}
Reply with ONLY JSON of exactly this shape, with no preamble and no code fence:

{"edits": [{"find": "...", "replace": "...", "reason": "..."}]}

- `find` is copied character for character from the passage, within a single paragraph, and long enough to occur only once — a phrase, not a lone common word. Quote only the passage the reader sends, never these instructions or their examples.
- Edits must not overlap.
- `replace` is the new wording; use "" to cut the text.
- `reason` is a few words on why.
- Give at most about ten edits, the most important first.
- If nothing needs changing, reply {"edits": []}.
- Removing a bracketed author direction is itself an edit.

