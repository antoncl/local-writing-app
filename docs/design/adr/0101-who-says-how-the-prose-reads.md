# ADR-0101: Who says how the prose reads — the prompt, the author's style, or the voice

**Status:** Accepted — 2026-10-24, Anton Lauridsen, after revision against two cold implementing
threads. Text by Claude, from a conversation with Anton about a *Narration Conventions* note that
"doesn't hit the mark".
Epic #2611.
**Context verified against `1cd8761b` (2026-10-24).**

## Context

Three things now tell a model how to write a scene's prose, and nothing says which owns what.

- **The built-in prose prompts.** Ten built-ins write or edit manuscript prose. Nine include both
  *Prose generation settings* (`backend/app/builtin_library/prompts/prose-settings.md`) and
  *Character voice in prose* (`character-voice.md`): Continue, Describe, Draft scene, Expand,
  Finalize roleplay, Line edit, Rephrase, Shorten, and *Show, don't tell*. The tenth, Tighten
  grammar, includes neither, and corrects mechanics a book may set on purpose (dashes, numbers,
  fragments). Craft rules are scattered and uneven:
  - Draft scene states the fullest set: *One continuous stretch of time*, *One mind* (branching
    on the narration mode, with a no-viewpoint fallback that tells the author who it chose),
    *Trust the reader*, and "Keep dialogue tags plain".
  - Continue has its own (match the voice, tense and rhythm; a passage, not the scene; no
    summing-up ending; no invented events) and no viewpoint or trust-the-reader rule.
  - The editing prompts carry the rule their job needs: Line edit names filter words and telling;
    Shorten names padding and keeps "a feeling or fact the passage states" as a beat; *Show,
    don't tell* is one craft rule; Finalize roleplay folds the viewpoint character's interiority
    into the narration.
- **The viewpoint is resolved two ways.** Draft scene and Continue read `resolved_narration`, which
  inherits down the manuscript (ADR-0079). Finalize roleplay reads `pov(scene)`, the scene's own
  field only.
- **The viewpoint character's entry reaches five of the ten.** Draft scene and Continue place it
  with `use(narration.character)`; *Passage context* (`passage-context.md`) does the same for
  Expand, Describe and Rephrase. Line edit, Shorten, *Show, don't tell*, Finalize roleplay and
  Tighten grammar don't place it.
- **Voice.** *Character voice in prose* treats a character's notes as tendencies, not a quota, and
  says a voice is carried by "register, sentence length, rhythm, what they leave unsaid". Nothing
  says a voice also decides what the narration notices and how it thinks while that character is
  the viewpoint. No built-in schema has a voice field.
- **A conventions note.** Anton's projects keep a `lore:note` called *Narration Conventions* with
  context policy *always*. The project prompt that builds it, *Narration conventions*, keeps it to
  copyedit mechanics and policy, and excludes "tone, rhythm, imagery, word choice" as belonging to
  a voice. The note has outgrown that: it holds paragraph construction, a stance on diction
  ("frank and direct"), a pointer to a narrator entry, and a *Naming conventions* section.
- **Only the author sets a context policy.** `context_policy` is `ai_proposable: False`
  (`services/project/default_schema.py`; ADR-0057, ADR-0059 §F), and an absent value resolves to
  *auto*. A note an AI commit creates is *auto* until the writer changes it.
- **Lore is layered, and an *always* entry rides down the chain.** A book sees every lore entry of
  the ancestors it declares (ADR-0039; `list_lore_entries` in `services/project/lore.py`). An
  inherited *always* entry goes out with the book's sends (`_lore_policy_ids` in
  `services/ai/lore_selection.py`), in a conversation or a one-shot, unless the prompt calls
  `no_lore()`, and not on a commit turn (ADR-0092 Amendment 1). A nearer layer can override an
  inherited entry's body only by **replacing it whole** (ADR-0039 Amendment 4).
- **The model can't see which layer an entry comes from.** A lore element carries its entry type
  as the tag and `id`, `name` and `aliases` as attributes (`_render_lore_entries`,
  `services/ai/lore_block.py`), and no template global exposes a layer.
- **The lore-writing prompts have their own register.** *Lore register* ("write every field and
  the body like a series bible") is included by Revise entry and Follow a change, and neither
  includes the prose snippets. *Prose generation settings* already keeps POV and tense out of lore
  and chat. That separation keeps a manuscript's manner out of reference lore.
- **Draft scene frames everything as working notes.** "The notes you are given on characters and
  the world, are the author's working notes … not text for the reader." That is right for world
  lore and wrong for a note that says how to write.
- **Caching orders a prompt by how often its text changes** (ADR-0084): what rarely changes comes
  first. *Prose generation settings* changes with the scene's narration. *Character voice in
  prose* is static text.

What prompted this: the prose the app writes is its core value, and the note meant to steer that
prose steers mostly punctuation. Before improving the note or the prompts, the division of work
has to be settled, or each improvement lands in whichever place is open at the time.

## Decision

1. **A hierarchy, narrowest wins.** How the prose reads is decided at four levels, each owning only
   what holds at its scope:
   - **Craft**: holds for any book. The built-in prose prompts own it (decision 2).
   - **Style**: this author's, this series' or this book's choices, whoever is narrating. Style
     notes own it, one per layer that has something to say (decisions 4–5).
   - **Voice**: holds while one character narrates or speaks. That character's entry owns it
     (decision 6).
   - **Brief**: holds for this scene. The scene's own fields, unchanged.

   Brief beats voice, voice beats style, a book's style beats its series', a series' beats the
   author's, and any of them beats craft. One limit: **a voice may shift the style, never the
   mechanics.** A euphemistic character speaks in euphemisms, but no voice italicises thought in a
   book that doesn't.

2. **Craft is one static snippet, *Prose craft*.**
   - **Its content** is the rules that hold for any prose, each a default the levels above may
     override, with a one-clause reason:
     - no skipped time inside what is written
     - viewpoint discipline
     - a moment shown once and not explained afterwards
     - no summing-up ending
     - plain dialogue tags
   - **It contains no template logic.** It states the viewpoint rule for each narration mode in
     plain prose: one mind in first person and close third, deliberate moves between minds at a
     paragraph break in omniscient, no one's thoughts in objective. *Prose generation settings*
     says which mode and which character apply. That keeps it cacheable and copyable.
   - **It also holds** the rule for which notes are instructions (decision 7) and the
     narrowest-wins order (decision 1).
   - **Stock-phrase bans are not in its first version.** Which phrases to ban is settled by reading
     measured drafts, and they are added then.

3. **The ten prose built-ins say it the same way.**
   - **Shared snippets, in caching order.** Each includes *Prose craft*, then *Character voice in
     prose*, then *Prose generation settings*: static first, per-scene last.
   - **The viewpoint character's entry.** *Character voice in prose* places it, so all ten send it.
     A prompt that already places it doesn't duplicate it, since a send dedupes lore by id.
   - **One resolution.** Finalize roleplay moves to `resolved_narration`, so every prose prompt
     reads the viewpoint the same way.
   - **What stays in a prompt** is what belongs to its task:
     - Draft scene keeps that the scene is one continuous stretch from first line to last, in the
       brief's order, and keeps its markers. When no viewpoint is set, it also tells the author in
       a line which character it chose, since only a conversation can address the author.
     - Continue keeps its seam rules.
     - The editing prompts keep their scope. Shorten still keeps a stated feeling as a beat, and
       Tighten grammar still fixes only grammar.
   - **Editing prompts apply *Prose craft* only to the words they write.** The task says what may
     change, and craft says how new words read. Shorten doesn't rewrite a told feeling into a
     shown one; *Show, don't tell* does, because that is its task.
   - **Tighten grammar gains the snippets** so it no longer "corrects" the book's mechanics.
   - **Copies are not updated.** A writer's copies of these built-ins, and any project snippet
     shadowing one of them by title, keep their own text (ADR-0049: clone, not fork). The changes
     reach a copy only when its owner takes them.

4. **A style note holds two things, each rule with one clause of why.**
   - **Mechanics**: how thought, dialogue, interruptions, flashbacks, documents, emphasis,
     numbers and invented terms are set on the page; content limits; how exposition reaches the
     reader.
   - **Manner**: the stance every voice shares, such as diction (frank or euphemistic), how far
     figurative language goes and how paragraphs are built. It also holds **a short list of things
     this author or book never does**, drawn from drafts the writer rejected. That list is not
     generic; the generic one is *Prose craft*'s.

   An example only where a rule isn't obvious. A rule the prose prompts have no occasion to apply,
   such as a scene-break marker (Draft scene writes one scene with no break inside it), may stay for
   the writer's own use, but the builder doesn't ask for one. A style note is reference material,
   so it is written in *Lore register*: terse and declarative.

5. **Each layer's style note says only what that layer decides, and names its departures.**
   - **Where each note lives.** The author's style lives at the outermost layer that holds it, a
     series' style at the series folder, and a book's at the book.
   - **They are ordinary notes, set to *Always* by the writer.** A book's sends then carry every
     note in its chain. The builder can't set the policy (Context); its last message tells the
     writer to set it, and that step is part of the journey.
   - **A nearer note names its departures.** The model can't see layers, so a note that changes an
     inherited rule says so in its own text: "Inner thought: italicised; this book departs from the
     series here." A note that departs from nothing restates nothing.
   - **The builder takes the notes it builds on as an input.** The writer picks the inherited style
     notes in an optional context-pick input. The builder reads those and proposes only the
     differences. Nothing needs a layer exposed to templates, and a writer can author it.
   - **Overriding an inherited note's body is not the route.** A body override replaces the whole
     body, so a book changing one rule would carry a stale copy of every other rule.

6. **A voice is how a mind meets the page, and it lives in the character's entry.** It has two
   parts, because they apply at different times:
   - **The narrating voice** applies only while the character is the viewpoint: what they notice
     first and never notice, what they compare things to, how they name what they see, how deep
     the interiority runs and how a thought surfaces, and how the body registers.
   - **The speaking voice** applies whenever they speak: register, sentence length, rhythm, and
     what they leave unsaid.

   A voice also includes **a short sample passage** with that character as the viewpoint, approved
   by the writer. It is the strongest steer a model gets.
   - **A narrator with a persona of its own** (omniscient, distant, a framed teller) gets a
     character entry with only the narrating voice.
   - **Where in the entry it goes** (body or a field of the writer's own schema) is the writer's
     call; this decision adds no field.
   - **The voice section is written in *Lore register*,** except the sample, which is prose by
     design.
   - ***Character voice in prose* says both parts:** the narrating voice belongs to the viewpoint
     character only, the speaking voice to every speaker.

7. **Prose prompts follow style and voice; lore prompts describe them.**
   - **In a prose prompt,** *Prose craft* says that a note setting out how the book or a voice is
     written is an instruction to follow, unlike notes about the world. The model tells them apart
     by what a note says, not by a kind or a flag. Draft scene's working-notes sentence is narrowed
     to match, so the prompt doesn't say both.
   - **In a lore prompt** (Revise entry, Follow a change), style notes and voice sections are
     **content**, not instructions. The entry is written in *Lore register*, never in the book's
     manner or a character's voice. Both prompts gain the sentence saying so. It goes in the
     prompts, not in *Lore register*, so a project that shadows *Lore register* keeps it.
   - **When Revise entry works on an entry that has, or is asked to gain, a voice section,** it
     follows decision 6's shape. Its length guidance counts the sample as part of the entry.
   - **Other prompts are unchanged.** That covers Roleplay, Impersonate, the plot prompts, Summarize
     scene and Check against lore. They still receive *always* style notes; whether they should is
     ADR-0092's question, not this one's.

8. **Two things leave the style notes.** POV and tense stay in the narration fields (ADR-0079).
   Naming conventions move to their own world note, since they govern invented names, not prose.
   How that note reaches the prompts that coin names is not decided here.

## Anti-goals

- **Not a new node kind, entry type, field, context policy or template global** for style or
  voice. All are ordinary entries any writer can author; the built-ins must stay reproducible by a
  user.
- **Not layer precedence the model has to infer.** It sees no layers. A departure is written in the
  nearer note, or it doesn't exist.
- **Not one style note overridden down the chain** (decision 5).
- **Not the AI setting a context policy.** The writer sets *Always*; the builder only says to.
- **Not the author's taste in a built-in.** No built-in says "no italics for thought". Nor is a
  shadowed *Prose craft* the home for a book's style: style is lore the writer reads in the lore
  pane, not a fork of a snippet.
- **Not template logic in *Prose craft*** (decision 2). A Jinja branch per mode would make the
  shared block vary by scene and break its caching.
- **Not a sample passage in a style note.** A sample has a voice, and in a book with several
  viewpoints it would pull them all toward one.
- **Not the manuscript's manner or a character's voice in lore.**
- **Not an editing prompt rewriting beyond its task** under cover of craft.
- **Not POV or tense copied into a note.**
- **Not a scoring feature in the app.** Measurement is a development method:
  [`measuring-prose-quality.md`](../measuring-prose-quality.md).

## The journey that defines done

1. The writer opens the outermost project of their chain and runs the style builder on pasted
   pages from an earlier book. It proposes a note with Mechanics and Manner and a reason per rule.
   The note has a "never" list of three to six items and no POV, tense, scene-break or naming rules.
   The writer commits it and, as the builder's last message says, sets it to *Always include*.
2. In the book, the writer runs the builder again and picks the author note as the style it builds
   on. The builder asks only what this book does differently. It proposes a book note holding just
   the departures, each saying it departs. The writer commits it and sets it to *Always include*.
3. The writer adds a narrating voice, a speaking voice and a 150-word sample to the viewpoint
   character's entry.
4. The writer runs Draft scene, then Continue, then Shorten on a paragraph in the same scene. All
   three requests carry *Prose craft*, both style notes and the viewpoint character's entry, checked
   on the outgoing requests. The drafts follow the book's departure and otherwise the author's
   style. Shorten keeps a stated feeling.
5. A second character, whose entry says she talks around things, speaks in euphemism. The narration
   around her stays frank, and what it notices is the viewpoint character's, not hers.
6. Tighten grammar leaves the book's spaced em-dashes alone.
7. The writer runs Revise entry on the viewpoint character. The proposed fields read like a series
   bible, terse and in third person, not like the manuscript or the character.
8. A second book whose style note says "descriptive dialogue verbs welcome" gets them from Draft
   scene, though *Prose craft* defaults to plain tags.

## Slices

- **S1: *Prose craft*.**
  - Write the snippet from the rules the prompts state today (decision 2), and include it in the
    ten in the decision 3 order.
  - *Character voice in prose* places the viewpoint character, and *Prose generation settings*
    names it beside the mode and tense (today it shows only the mode and tense).
  - Move Finalize roleplay to `resolved_narration`.
  - Narrow Draft scene's working-notes sentence, take the moved rules out of Draft scene, and add
    the lore-side sentence to Revise entry and Follow a change.
  - Update `docs/prompts/reference.md` where it describes these snippets.
  - *Not:* stock-phrase bans, or new rules beyond what the prompts state today.
- **S2: The style builder.**
  - Rewrite the *Narration conventions* prompt to decisions 4–5:
    - infer from pasted pages
    - test taste by contrast (two short versions of one moment: "which is closer?")
    - take the inherited style notes as an optional pick input and propose only departures
    - write in *Lore register*
    - end by telling the writer to set *Always include*
  - Its repo deliverable is the prompt's text, committed with the measurement fixtures so the
    builder test can run it.
  - *Not:* a built-in yet.
- **S3: Voice.**
  - *Character voice in prose* says both parts of a voice and when each applies.
  - Revise entry follows decision 7's voice rule.
  - *Not:* a schema field.

S1 and S2 touch different files and may run in parallel. S3 follows S1, since both edit *Character
voice in prose*.

## Out of scope

- **Whether the style builder ships as a built-in.** Deferred until measured drafts show the
  rewritten prompt makes a better note.
- **Which stock phrases *Prose craft* bans.** Settled by reading drafts.
- **Roleplay's turns.** They are conversation, not manuscript prose. Finalize roleplay, which writes
  prose, is in.

## Rejected

- **Widen the note only, leave the prompts alone.** The universal rules would be retyped into every
  book's note, and Continue would still be held to less than Draft scene.
- **Fold voice into a style note.** A book with several viewpoints would get one voice.
- **One style note, overridden per layer.** It means whole-body replacement (decision 5).
- **Show the model each entry's layer**, or add a template global for it. That changes the lore
  render or the vocabulary for every prompt, to serve an ordering that one sentence in the nearer
  note already states.
- **A Jinja branch per narration mode in *Prose craft*.** It is cache-hostile and harder to copy.
  The per-scene fact belongs in *Prose generation settings*.
- **The lore-side sentence in *Lore register*.** A project shadowing that snippet would lose it.
- **A dedicated style kind the prompts can find by type.** A special case a writer can't reproduce,
  for a job decision 7's one sentence does.

## Amendment 1 — *Prose craft* has four rules, and the viewpoint rule names what it excludes

- **Status:** **Accepted** — 2026-10-25 (Anton), approved with the snippet's text. Issue: #2619 (S1).
- **Amends** decision 2's list of rules. Everything else in decision 2 stands: static text, no
  template logic, a one-clause reason per rule, the instruction rule and the narrowest-wins order.

### What prompted it

The harness's judge calibration (#2615; the outcome is recorded on #2611) had the writer answer
the decision 2 rules as yes/no questions on 128 passages. Two things came out of the reading,
not from guessing:

- **"Explained afterwards" and "summing-up ending" are one failure to the writer.** A planted
  mid-passage line, *"The laugh meant he had stolen the casks."*, was marked as a summing-up with
  the note "though not the last paragraph". What the writer counts is an outside narrator telling
  the reader what something means, wherever it stands. What the writer does **not** count is the
  viewpoint character reading what they see, in their own terms: *"It was the surest sign that he
  was lying"* was judged Ines's interiority. A rule against all interpretation would flatten close
  third.
- **Narration noticing what the viewpoint character couldn't is the commonest natural failure**
  (12 of 70 natural passages), more than slips into another mind (7). The draft prompts' rule
  ("holds only what the viewpoint character perceives") already implies it but never names it.

### Decision

- The two rules become one: **the narrator never tells the reader what something means.** A moment
  is shown once and left; no sentence afterwards says what it meant or what someone realized, and
  no closing paragraph steps back to sum up or look ahead. The viewpoint character may read what
  they see, in their own terms and in the moment; an outside voice explaining it may not.
- **The viewpoint rule names what it excludes:** how the viewpoint character looks from outside,
  what happens out of their sight, and what they learn only later.
- *Prose craft* therefore states four rules: no skipped time, viewpoint discipline, the narrator
  never explains, plain dialogue tags. The text is fixed in `prose-craft.md` (#2619).

### Not changed

No new rule beyond what the prompts already stated: the merge keeps both contents, and the
viewpoint rule spells out the one Draft scene already had. Two of Draft scene's own sentences move
in with them, approved after review (#2620): a stranger is named only once the scene gives the
name (#2604), and characters rarely say outright what they want or feel. Stock-phrase bans stay
out (decision 2).

## Amendment 2 — two rules sharpened from the S1 blind pairs

- **Status:** **Accepted** — 2026-10-26 (Anton), approved with the wording. Issue: #2621.
- **What prompted it.** S1 was preferred in 13 of 20 blind pairs, below the 15 bar. The sentences
  the writer cut on the S1 side were narrator verdicts on a moment ("it cost her nothing", "taken
  one way, a disaster") and conversation reported instead of heard.
- **Decision.** The narrator rule says the narration passes no verdict (what a moment meant, cost
  or how to take it), names judging beside explaining, and gives the writer's own test: a sentence
  that would fit after "the viewpoint character thought" may stay (no pronoun, since the snippet serves every viewpoint); the narrator's opinion is cut. The no-skipped-time
  rule adds that a conversation is heard, not reported, **unless the brief asks for it**: a skip is
  the author's decision, never the drafter's.
