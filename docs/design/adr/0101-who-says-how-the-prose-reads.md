# ADR-0101: Who says how the prose reads — the prompt, the author's style, or the voice

**Status:** Accepted — 2026-10-24, Anton Lauridsen. Text by Claude, from a conversation with
Anton about a *Narration Conventions* note that "doesn't hit the mark". Epic #2611.
**Context verified against `1cd8761b` (2026-10-24).**

## Context

Three things now tell a model how to write a scene's prose, and nothing says which owns what.

- **The built-in prose prompts.** Nine built-ins write or rewrite manuscript prose; each includes
  the *Prose generation settings* snippet (`backend/app/builtin_library/prompts/prose-settings.md`)
  and the *Character voice in prose* snippet (`character-voice.md`): Continue, Describe, Draft
  scene, Expand, Finalize roleplay, Line edit, Rephrase, Shorten, Show don't tell. **Only Draft
  scene states craft rules**: *One continuous stretch of time*, *One mind* (branching on the
  narration mode), *Trust the reader*, and "Keep dialogue tags plain" (the rule list in
  `draft-scene.md`). Continue keeps only its passage-not-scene and no-summing-up rules
  (`continue.md`); the other seven state none. So a passage from Continue is held to less than a
  scene from Draft scene, in the same book.
- **Voice.** *Character voice in prose* says how to use a character's voice notes — tendencies,
  not a quota — and that a voice is carried by "register, sentence length, rhythm, what they leave
  unsaid": speech only. Nothing says a voice also governs what the narration notices and how it
  thinks when that character is the viewpoint. No built-in schema has a voice field, and Anton's
  character entries describe voice in passing ("Her voice is low and unhurried").
- **A conventions note.** Anton's projects keep a `lore:note` called *Narration Conventions*,
  context policy *always*, so conversations and one-shot runs carry it unless a prompt calls
  `no_lore()`; a commit turn does not (ADR-0092, as amended). It is built by a project prompt,
  *Narration conventions* (`prompt:general`, in the project's `prompts/` folder, not a built-in).
  That prompt confines the note to copyedit mechanics and policy (inner thought, dialogue tags,
  dashes, flashbacks, documents, scene breaks, emphasis, numbers, content limits, exposition) and
  excludes "tone, rhythm, imagery, word choice" as belonging to a voice. The note it produced has
  outgrown that scope: it also holds paragraph construction (motivation–reaction units), a stance
  on diction ("frank and direct", no euphemism outside dialogue), a pointer to a narrator entry,
  and a *Naming conventions* section for the world.

Four further facts bear on the decision:

- **Lore is layered, and an *always* entry rides down the chain.** A book sees every lore entry of
  the ancestors it declares (ADR-0039; `list_lore_entries` in `services/project/lore.py` lists the
  whole chain), and an inherited *always* entry goes out with the book's sends
  (`_lore_policy_ids` in `services/ai/lore_selection.py` reads that listing). A nearer layer can
  override an inherited entry's fields, title and body, but **a body is overridden only by whole
  replacement** (ADR-0039 Amendment 4; `_save_lore_override` in `lore.py`). Two entries with
  different ids and the same title, at different layers, are both listed and both sent.
- **The model cannot see which layer an entry comes from.** A lore element is rendered with its
  entry type as the tag and `id`, `name` and `aliases` as attributes (`_render_lore_entries` and
  the comment above it, `services/ai/lore_block.py`); no layer.
- **The lore-writing prompts have their own register.** *Lore register* (`lore-register.md`) —
  "write every field and the body like a series bible" — is included only by Revise entry and
  Follow a change, and neither includes the prose snippets. *Prose generation settings* already
  keeps POV and tense out of lore and chat, so a first-person manuscript can't push a character's
  fields into first person. The same separation is what keeps a frank, close, sensory manuscript
  style out of terse reference lore.
- **Draft scene frames everything it is given as working notes.** It says "the notes you are given
  on characters and the world, are the author's working notes … not text for the reader". That is
  right for world lore and silent on a note that says *how to write*, so a style note reaches the
  model as one more working note.

What prompted this: the prose the app writes is its core value, and the note meant to steer that
prose steers mostly punctuation. Before improving the note or the prompts, the division of work
has to be settled, or each improvement lands in whichever place is open at the time.

## Decision

1. **A hierarchy, narrowest wins.** How the prose reads is decided at five levels, each owning
   only what holds at its scope:
   - **Craft** — holds for any book. Owned by the built-in prose prompts (decision 2).
   - **Style** — this author's, this series' or this book's choices, whoever is narrating. Owned
     by style notes, one per layer that has something to say (decisions 3–4).
   - **Voice** — holds while one character narrates or speaks. Owned by that character's entry
     (decision 5).
   - **Brief** — holds for this scene. The scene's own fields, unchanged.

   Brief beats voice, voice beats style, a book's style beats its series', a series' beats the
   author's, and any of them beats craft. One limit: **a voice may shift the style, never the
   mechanics** — a euphemistic character speaks in euphemisms (Anton's note already says so), but
   no voice italicises thought in a book that doesn't.

2. **Craft is one snippet, *Prose craft*, and every prose prompt says it the same way.** The
   rules any good prose needs — no skipped time inside a scene, viewpoint discipline per narration
   mode, a moment shown once and not explained, no summing-up endings, freedom from the stock
   phrasing models fall into — move out of Draft scene's text into *Prose craft*. Each rule is a
   default the levels above may override, with a one-clause reason. The snippet also carries the
   framing of decision 6, so it is written once. The nine prose built-ins include **the same three
   snippets in the same order** — *Prose generation settings*, *Prose craft*, *Character voice in
   prose* — so a passage from Continue is held to what a scene from Draft scene is. Draft scene
   keeps only what is about drafting a whole scene (one continuous stretch, the order of events,
   its markers).

3. **A style note holds two things, each rule with one clause of why.**
   - **Mechanics**: how thought, dialogue, interruptions, flashbacks, documents, emphasis, numbers
     and invented terms are set on the page; content limits; how exposition reaches the reader.
   - **Manner**: the stance every voice shares — diction (frank or euphemistic), how far figurative
     language goes, how paragraphs are built — and **a short list of things this author or book
     never does**, drawn from drafts the writer rejected, not a generic list (that is *Prose
     craft*'s).
   An example only where a rule isn't obvious. A rule the prose prompts have no occasion to apply
   (a scene-break marker: Draft scene writes one scene, with no break inside it) may stay for the
   writer's own use, but the builder prompt no longer asks for it.

4. **Each layer's style note says only what that layer decides, and names its departures.** The
   author's preferred style lives at the outermost layer that holds it, a series' at the series
   folder, a book's at the book. They are separate ordinary notes with policy *always*, so a book's
   sends carry every one in its chain. Because the model can't see layers (Context), **a nearer
   note that changes an inherited rule says so in its own text**: "Inner thought: italicised — this
   book departs from the series here." A note that departs from nothing restates nothing. The
   builder prompt reads the inherited style notes and writes only the difference.
   - Overriding an inherited note's body is **not** the route: a body override replaces the whole
     body, so a book changing one rule would carry a stale copy of every other one.

5. **A voice is how a mind meets the page, and it lives in the character's entry.** It has two
   parts, because they apply at different times:
   - **The narrating voice** — applies only while the character is the viewpoint: what they
     notice first and what they never notice, what they compare things to, how they name what they
     see, how deep the interiority runs and how a thought surfaces, how the body registers.
   - **The speaking voice** — applies whenever they speak: register, sentence length, rhythm, what
     they leave unsaid.
   Plus **a short sample passage** with that character as the viewpoint, approved by the writer —
   the strongest steer a model gets. For a narrator with a persona of its own (omniscient, distant,
   a framed teller), that narrator gets a character entry and only the narrating voice. Where in the
   entry this is written (body or a field of the writer's own schema) is the writer's call; this
   decision adds no field. *Character voice in prose* grows to say both parts: the narrating voice
   is the viewpoint character's only, the speaking voice is every speaker's.

6. **Prose prompts follow style and voice; lore prompts describe them.**
   - In a prose prompt, *Prose craft* tells the model that a note setting out how the book or a
     voice is written is an instruction to follow, unlike notes about the world, and that where two
     disagree the narrower one wins (decision 1). The model tells them apart by what a note says,
     not by a kind or a flag.
   - In a lore prompt (Revise entry, Follow a change), style notes and voice sections are
     **content**, not instructions: the entry is written in *Lore register*, never in the book's
     manner or the character's voice. A voice section is itself written in that register — terse
     and declarative — except its sample passage, which is prose by design. Revise entry and Follow
     a change gain the sentence saying so, since an *always* style note reaches them too.

7. **Two things leave the style notes.** POV and tense stay in the narration fields (ADR-0079).
   Naming conventions move to their own world note, since they govern invented names, not prose;
   how that note reaches the prompts that coin names is not decided here.

## Anti-goals

- **Not a new node kind, entry type, field or context policy** for style or voice. All are
  ordinary entries any writer can author through the public paths; the built-ins must stay
  reproducible by a user.
- **Not layer precedence the model has to infer.** It sees no layers; a departure is written in
  the nearer note or it doesn't exist.
- **Not one style note overridden down the chain.** A body override is a whole copy (decision 4).
- **Not the author's taste in a built-in.** No built-in says "no italics for thought" or "said
  only"; *Prose craft* states craft every book shares, as overridable defaults. Nor is a shadowed
  copy of *Prose craft* the home for a book's style: style is lore the writer reads in the lore
  pane, not a fork of a snippet.
- **Not a sample passage in a style note.** A sample has a voice; in a book with several
  viewpoints it would pull them all toward one.
- **Not the manuscript's style or a character's voice in lore.** A lore prompt never writes in
  them, however strongly the style note is worded.
- **Not a generic list of model clichés in a style note.** That belongs to *Prose craft*.
- **Not POV or tense copied into a note** — the narration fields own them and a copy drifts.
- **Not a scoring or evaluation feature.** Measuring drafts against fixed scene briefs is how the
  slices are judged, not part of the app: the method, its success criteria and who judges are in
  [`measuring-prose-quality.md`](../measuring-prose-quality.md).

## The journey that defines done

1. In the author's outer folder, the writer runs the style builder on pasted pages from an earlier
   book. The note has Mechanics and Manner, a reason per rule, a "never" list of three to six items,
   and no POV, tense, scene-break or naming rules.
2. In the book, the writer runs the builder again. It shows the inherited author note, asks only
   what this book does differently, and proposes a book note holding just the departures, each
   saying it departs.
3. The writer adds a narrating voice, a speaking voice and a 150-word sample to the viewpoint
   character's entry.
4. The writer runs Draft scene, then Continue in the same scene. Both requests carry *Prose craft*,
   both style notes and the viewpoint character's entry — checked on the outgoing requests. Both
   drafts follow the book's departure and otherwise the author's style.
5. A second character, whose entry says she talks around things, speaks in euphemism; the
   narration around her stays frank, and what it notices is the viewpoint character's, not hers.
6. The writer runs Revise entry on the viewpoint character. The proposed fields read like a series
   bible — terse, third person — not like the manuscript or the character.
7. A second book whose style note says "descriptive dialogue verbs welcome" gets them from Draft
   scene, though *Prose craft* defaults to plain tags.

## Slices

- **S1 — *Prose craft*.** Extract the universal rules from Draft scene into the snippet, phrase
  them as reasoned defaults, add the decision 6 framing and the narrowest-wins rule, and include it
  in the nine prose built-ins in the fixed order. Add the lore-side sentence to Revise entry and
  Follow a change. *Not:* new craft rules beyond what Draft scene states today; those come from
  measured drafts.
- **S2 — The style builder.** Rewrite the *Narration conventions* prompt to decisions 3–4: infer
  from pasted pages, test taste by contrast (two short versions of one moment, "which is closer?"),
  read the inherited style notes and propose only the departures, rules with reasons. *Not:* a
  built-in yet (see below).
- **S3 — Voice.** *Character voice in prose* says both parts of a voice and when each applies;
  Revise entry knows what a voice section holds. *Not:* a schema field.

S1 and S2 touch different files and may run in parallel; S3 follows S1, since both edit the prose
prompts' shared snippets.

## Out of scope

- **Whether the style builder ships as a built-in.** Deferred until measured drafts show the
  rewritten prompt produces a better note.
- **Which stock phrases *Prose craft* bans.** Settled by reading drafts, not in this document.
- **Roleplay's turns.** They are conversation, not manuscript prose; *Prose generation settings*
  stays out of them for the same reason. Finalize roleplay, which writes prose, is in.

## Rejected

- **Widen the note only, leave the prompts alone.** The universal rules would be retyped into
  every book's note, and Continue would still hold passages to less than Draft scene.
- **Fold voice into a style note.** A book with several viewpoints would get one voice.
- **One style note, overridden per layer.** Whole-body replacement (decision 4).
- **Show the model each entry's layer.** It would let the model order the notes itself, but it
  changes the lore render for every entry to serve one ordering a sentence in the nearer note
  already states.
- **A dedicated style kind the prompts can find by type.** A special case a writer can't
  reproduce, for a job decision 6's one sentence does.
