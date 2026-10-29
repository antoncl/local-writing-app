# How your prose is steered

> User guide. When the app writes or edits prose for you, four things tell the
> model how it should read: the app's own craft rules, your style notes, your
> characters' voices, and the scene's brief. This guide says what each one is
> for, which one wins when they disagree, and how to check what was sent.

The prose actions are Draft scene, Continue, Expand, Describe, Rephrase, Shorten,
Line edit, *Show, don't tell*, Tighten grammar and Finalize roleplay. Every one of
them sends the model *Prose craft*, your style notes, the viewpoint character's
voice and the narration settings, so a passage from Continue is held to the same
standard as a scene from Draft scene.

## What a prose action sends

- **Prose craft.** A short set of rules the app ships, for any book: no skipped
  time inside a passage, one viewpoint held steadily, a narrator who never tells
  the reader what a moment meant, and plain dialogue tags. Each is a default, not
  a law.
- **Your style notes.** Every note whose **Context policy** is *Always include*
  goes out with every prose action. A style note says how *this* book, series or
  author is written: how thought and dialogue are set on the page, how frank the
  diction is, what the book never does.
- **The viewpoint character's entry.** The character whose eyes the scene is seen
  through, from the scene's narration fields. If their entry describes a voice,
  that voice shapes the narration as well as their lines.
- **The narration settings.** The point of view and tense, from the scene, or
  inherited from its chapter, act or project.
- **The brief.** For Draft scene and Continue, the scene's summary. For Expand,
  Describe and Rephrase, the passage you selected and the text around it. The
  other editing actions see only what you selected.

Everything else in your lore is world material: what happened, who is who. The
model uses it as facts for the scene, never as text for the page. It tells a style
note from a world note by what the note says, so a plain note with style rules in
it works the same as a style note.

## Which one wins

The four are arranged from broad to narrow, and **the narrowest wins**:

1. **The brief** beats everything: "she shouts" in a brief beats a voice that
   never raises it.
2. **A character's voice** beats a style note, but only on how things are said. A
   voice never changes how things are set on the page: if the book italicises
   inner thought, it does so whoever narrates.
3. **A style note** beats *Prose craft*. A book's note beats its series' note, and
   a series' note beats the author's.
4. **Prose craft** holds wherever nothing narrower says otherwise. A style note
   that welcomes descriptive dialogue verbs gets them, though *Prose craft* asks
   for plain tags.

![Four stacked bands, broadest at the bottom. Prose craft: the app's defaults for any book. Style notes: author, series, then book, nearest wins. The viewpoint character's voice: what the narration notices and how it thinks, while they are the viewpoint. The brief: what happens in this scene. An arrow up the side reads "narrower wins". On the right, one box lists what every prose action sends: Prose craft, the style notes set to Always include, the viewpoint character's entry, the narration settings, and the brief.](prose-steering/levels.svg)

## Style notes

A style note holds two things, each rule in one line with a short reason:

- **Mechanics** — how inner thought, dialogue, interruptions, flashbacks,
  documents, emphasis, numbers and invented terms are set on the page; how far
  violence and intimacy go; how background reaches the reader.
- **Manner** — the stance every voice shares: frank or euphemistic, how far
  figures of speech go, how paragraphs are built. Then a short **Never** list,
  three to six things this book never does.

It leaves out what lives elsewhere:

- the point of view and tense, which are the narration settings
- any one character's voice, which belongs in their entry
- sample passages, since a sample has a voice and would pull every viewpoint
  toward it
- naming conventions, which are about the world, not the prose: keep them in a
  note of their own (see [Lore](#guide:lore), *Notes the AI always sees*)

**Notes stack by layer.** If your books sit inside a series or an author folder
(see [Getting started](#guide:getting-started)), each layer can have its own style
note, and a book sees every note in its chain. A nearer note doesn't repeat the
farther one; it names only what changes, and says so: "Inner thought: italicised;
this book departs from the series here." The model can't tell which layer a note
comes from, so the departure has to be written in the note.

### Building one

The built-in prompt **Build a style note** writes one with you.

1. Open the project that should hold the note: the outermost one for your own
   style, a book for what that book changes.
2. In the Lore pane, open **+** and choose **✨ Draft Style note**.
3. Paste a chapter or a few pages, your own or a published book whose style you
   want, and send. Or press **Send** with the box empty, and the builder tells
   you what to paste. It reads the rules off the page and says which it inferred
   and which need your call.
4. Where the pages leave something open, it shows you two short versions of one
   moment and asks which is closer.
5. In a book, pick the inherited style notes under **Style notes this builds on**.
   The builder then asks only what this book does differently.
6. Commit the note, then set its **Context policy** to *Always include*. The
   builder can't do that for you: only you decide what goes out with every
   prompt. Until you set it, the prose actions never see the note.

A new project starts with no style note. Until you add one, the prose follows
*Prose craft*, your narration settings, your characters' voices and the brief.

**A style note you made earlier as a plain Note keeps working:** the prose
actions read it the same way, as long as it is set to *Always include*. The
builder is offered only on Style notes, so to rework an older note with it, draft
a new Style note, paste the old note's text into your first message along with
any pages, and delete the old note once the new one is committed.

## Voices

A character's voice lives in their own entry, in two parts, because they apply at
different times:

- **The narrating voice** applies only while they are the viewpoint: what they
  notice first and never notice, what they compare things to, how deep their
  thoughts run and how a thought surfaces, how the body registers. It shapes the
  narration, not just their lines. When someone else is the viewpoint, the
  narration doesn't take it on, even in a scene they're in.
- **The speaking voice** applies whenever they speak: register, sentence length,
  rhythm, and what they leave unsaid.

Add **a short sample passage**, about 150 words with them as the viewpoint. It is
the strongest steer a model gets. The model writes *like* it, never *from* it: it
won't reuse its sentences or images.

**Revise entry** writes a voice section in these three parts when you ask it to.
A narrator with a personality of their own gets an entry with only a narrating
voice.

## Checking what was sent

Start Draft scene on a scene and open the **Context** door on its composer (see
[What the AI sees](#guide:ai-context), *Reading the Context door*). The editing
actions carry the same craft rules, style notes, voice and narration settings, so
those parts of what you see there hold for them too:

- **System** shows *Prose craft*, the voice instructions and the narration
  settings, as the model reads them.
- **Stable lore** and **Volatile lore** list the entries that went out. Your style
  notes are there if they are set to *Always include*, and so is the viewpoint
  character's entry. Open one to see exactly what the model received.

If a draft ignores your style, look there first: a style note that isn't in the
list was never sent.
