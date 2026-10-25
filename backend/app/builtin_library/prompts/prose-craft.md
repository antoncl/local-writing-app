---
id: prompt_ba9fe2af1e
title: Prose craft
entry_type: prompt:snippet
metadata:
  summary: "The craft rules that hold for any prose, for prompts that write or edit manuscript prose."
---
{#
  Prose craft snippet (#2619, ADR-0101 decision 2). The craft rules that hold
  for any book, written once so every prose built-in says them the same way.
  Include it FIRST, INSIDE a {% role %} block, before "Character voice in
  prose" and "Prose generation settings", in prompts that write or edit
  manuscript prose:
      {% include "Prose craft" %}
  The text is static on purpose: no template logic, so it caches (ADR-0084) and
  can be copied into a prompt of your own as it stands. What varies per scene
  (the viewpoint character, the mode, the tense) is in the snippets after it.
#}
## Prose craft
These hold for any prose you write here. Each is a default: a style note (for this book, its series or its author), a character's voice, or the scene's brief may set a different rule, and the narrowest wins. The brief beats a voice, a voice beats a style note, a book's note beats a series' or an author's, and any of them beats these. A voice may change how things are said, never how they are set on the page.

Some notes you are given say how the book is written, or how a character narrates and speaks: follow those as instructions. Every other note is about the world, and is material for the scene, not text for the page.

- **No skipped time inside what you write.** Play the moments out as they happen; don't cover hours or days in a sentence. A past the viewpoint character remembers is not a skip. *(A skip turns a scene into a summary.)*
- **Viewpoint discipline.** In first person and close third the narration holds one mind: only what the viewpoint character perceives, remembers, thinks and knows at that moment. Everyone else is seen from outside, and what they feel is the viewpoint character's guess, never fact. The narration doesn't notice what the viewpoint character couldn't, such as how they look from outside, what happens out of their sight, or what they only learn later. In omniscient narration, the narrator may enter any mind but moves between minds only at a paragraph break, never within an exchange. In objective narration, no one's thoughts or feelings are stated. *(A slip breaks the reader's place in the scene.)*
- **The narrator never tells the reader what something means.** Show a moment once, as action, speech, a gesture or a concrete detail, and leave it. No sentence afterwards says what it meant or what someone realized, and no closing paragraph steps back to sum up the scene or look ahead. The viewpoint character may read what they see, in their own terms and in the moment; an outside voice explaining it may not. *(Meaning the reader draws lands; meaning they're told doesn't.)*
- **Plain dialogue tags:** "said", or an action beat, and no adverbs on tags. *(The words carry the tone.)*


