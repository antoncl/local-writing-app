---
id: prompt_f826ca8db8
title: Notes reply format
entry_type: prompt:snippet
---
{#
  The reply contract of a lore-check prompt (#2490, ADR-0098): a prompt whose
  output handler is `inline_notes` answers with notes the writer reads, not
  with edits or replacement prose. Each note quotes a place in the passage and
  names the lore entry it contradicts. Include it INSIDE the system {% role %}
  block of any such prompt, after the prompt's own instructions (what to look
  for):
      {% include "Notes reply format" %}
  The app anchors a note only when its `quote` occurs exactly once in the
  selection, and drops a note whose `entry` is not an id of the lore the run
  sent, so the rules below are what make a note land.
#}
Reply with ONLY JSON of exactly this shape, with no preamble and no code fence:

{"notes": [{"quote": "...", "problem": "...", "entry": "..."}]}

- `quote` is copied character for character from the passage, within a single paragraph, and long enough to occur only once — a phrase, not a lone common word. Quote only the passage the reader sends, never these instructions or their examples.
- `problem` is one sentence naming what the passage says and what the lore entry says.
- `entry` is the `id` attribute of the lore entry the passage contradicts, exactly as it is given in the lore.
- Note only contradictions with the lore provided — not style, not plausibility, and not things the lore does not mention.
- Give at most about ten notes, the most important first.
- If nothing contradicts the lore, reply {"notes": []}.

