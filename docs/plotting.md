# Plotting

The **plot board** is a canvas for planning the shape of your story alongside the
prose. You lay out **cards** — one per beat or scene — arrange them, gather them
into **plotlines** (threads or arcs), and draw **causal links** to show what
leads to what. It sits next to your manuscript rather than replacing it: the board
is where you *plan*, and nothing you do there rewrites your draft.

This guide covers the board day to day. The cards and plotlines carry their own
fields (see **[Custom fields](#guide:custom-fields)**), and the Templates shelf is
a list like any other (see **[Views](#guide:views)**).

## Open the board

From the **≡ menu**, open **Plot board**. It's a workspace pane you can tile,
resize, and close like the others. There's one board per project — it's *the* plan
for this book, not one of many.

The **≡ menu** also has **Plot templates**, a separate shelf of reusable beat
structures — more on those at the end.

## What's on the board

Three kinds of thing share the canvas:

- **Cards** — the plot points. Each holds a **title**, a **synopsis**, and a
  **page-status** badge: **On the page** (tied to a written scene), **Off the
  page** (happens, but you're not writing it as a scene), or **Unwritten** (still
  just a plan).
- **Containers** — the faint boxes grouping cards by **act and chapter**. You
  don't create or name these; they mirror your manuscript structure, so a card's
  container shows *where in the book* it currently sits.
- **Plotlines** — the threads or arcs (the romance, the heist, a character's
  descent). A card can belong to a plotline, shown by a **colour stripe** and a
  named chip. Plotlines aren't lanes — a card carries its plotline's colour
  wherever it sits.

## Work with cards

- **Add one:** the toolbar's **New card** button drops a fresh card ("New card").
- **Edit inline:** click the title to rename it, click the synopsis to write it.
- **Card actions (⋮):** the kebab on a card opens a menu — **Open card** (its full
  editor, with fields), **Set plotline** (assign it to a thread, or
  **Unassigned**), **Mark off-page** / **Mark unwritten**, and **Delete card**.

## Cards and your manuscript

Cards and scenes are linked but independent, and you choose how tightly:

- **Seed from manuscript** (toolbar) creates one card per scene that isn't carded
  yet, each attached to its scene. It's safe to run repeatedly — already-carded
  scenes are skipped — so it's the quick way to get an existing draft onto the
  board.
- **Realize scene** (on a card's ⋮ menu) does the reverse: it mints a *new* scene
  from a planned card, and **Realize into…** lets you drop it under a chosen act or
  chapter. A card tied to a scene reads **On the page**.
- **Detach scene** breaks the link without touching the scene itself.

**Rearranging the board is planning, not editing.** Dragging cards saves only the
board's own layout — it never reorders your manuscript. The manuscript's reading
order is *shown* on the board (see **Layers**, below) so you can see plan against
draft, but the two only change when you tell them to (Realize, or editing the
manuscript directly).

## Plotlines

A plotline is a named thread you can follow across the book. Assign a card to one
from its ⋮ **Set plotline** menu; the card takes the plotline's colour. Click a
plotline's **focus** (eye) to light up that thread and dim everything else — handy
for reading one arc through a busy board.

You create plotlines from the **Templates** rail (toolbar **Templates**): pick
**Empty plotline** to start a bare thread, or a saved template to start one
pre-filled with its beats (see below).

## Causal links — what leads to what

Draw a **causal link** by dragging from one card's **out** handle to another
card's **in** handle: "this beat causes that one." To remove a link, click the
**×** at its midpoint (or select it and press **Delete**).

Causal links carry a check for you: if a link's *cause* is revealed **later** in
reading order than its *effect*, the link shows an amber **⚠** whose tooltip
explains the problem — a reader would meet the consequence before its cause. It's a
quiet nudge to reorder, not an error.

Causal links live on their own layer — turn them on with **Layers** (below).

## Layers

The **Layers** control toggles which relationships the board draws between cards:

- **Manuscript order** — the reading order of the draft.
- **Beat sequence** — the order of beats within a plotline.
- **Causal** — the "leads to" links you draw by hand.

Show one at a time to read the story a particular way, or combine them.

## Plot templates

A **plot template** is a reusable set of beats — a story structure you can drop
onto any project's board instead of typing the same skeleton each time. Think of
the shapes writers reach for again and again: the classic **three-act structure**,
or a romance beat sheet like *Romancing the Beat* — a named run of beats (an
inciting incident, a midpoint, a dark night of the soul, and so on) that many
stories share. A template captures one of those sequences once, so a new plotline
starts already scaffolded instead of blank.

Manage templates from the **≡ menu → Plot templates** shelf:

- Templates marked **Library** ship with the app and are read-only. **Clone** one
  (the ⧉ button) to get an editable copy of your own.
- Your own templates open in an editor, where you can shape their beats.

To use one, open the board's **Templates** rail and click the template — it drops a
**new plotline** onto the board seeded with that template's beats, ready to attach
to cards and reshape. The template itself is untouched; the plotline is your copy.

## Diagnostics and AI review

The toolbar's **Diagnostics** surfaces the board's own checks (like the
out-of-order warning, gathered up). If you've enabled AI and the plot-review prompt
is present, an **AI review** button offers a model's read of the plot — optional,
and only there when AI is on.

## Where to go next

- **[Custom fields](#guide:custom-fields)** — give cards and plotlines the fields
  your process needs.
- **[Views](#guide:views)** — the Templates shelf and every other list is a view
  you can shape.
- **[Getting started](#guide:getting-started)** — the wider tour, if you skipped
  ahead.
