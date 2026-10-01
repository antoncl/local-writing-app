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

Boxes, with cards flowing inside them, and a few free-floating threads:

- **Cards** — the plot points. Each holds a **title**, a **synopsis**, and a
  **page-status** badge: **On the page** (tied to a written scene), **Off the
  page** (happens, but you're not writing it as a scene), or **Unwritten** (still
  just a plan).
- **Chapter and act boxes** — one for **every** act and chapter, empty ones too.
  You don't create or name these; they mirror your manuscript structure, so a
  written card sits in the box of the chapter its scene is in, in manuscript order.
- **Decks** — dashed boxes you make yourself for cards that aren't in the
  manuscript yet (see **Decks**, below).
- **Loose cards** — a box that appears when some cards belong to no chapter or
  deck: unwritten cards without a deck, and cards whose scene sits at the top of
  the manuscript.
- **Plotlines** — the threads or arcs (the romance, the heist, a character's
  descent). A card can belong to a plotline, shown by a **colour stripe** and a
  named chip. Plotlines aren't lanes — a card carries its plotline's colour
  wherever it sits.

**Cards flow; only boxes are placed by hand.** A card has no spot of its own: it
takes its place inside its box, after the card before it. Boxes size themselves to
what they hold. You drag the **outermost boxes** (by their title bar) and the
plotlines to wherever you like, and everything inside a box moves with it; boxes
nested inside another box stay put. Dragging a box never moves your manuscript.

## Work with cards

- **Add one:** the toolbar's **New card** button makes a fresh card ("New card"),
  which lands in **Loose cards**; a deck's own **New card** makes one in that deck.
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
- **Write as scene** (on a card's ⋮ menu) does the reverse: it mints a *new* scene
  from an unwritten card, and **Write into…** lets you drop it under a chosen act or
  chapter. A card you've planned in a chapter (see below) skips the choice and is
  written right where it is planned. A card tied to a scene reads **On the page**.
- **Attach scene…** (on an unattached card's ⋮ menu) binds the card to a scene that
  already exists. The picker lists only scenes no other card holds.
- **Detach scene** breaks the link without touching the scene itself.

A card tied to a scene shows that scene's title and summary, not text of its own:
editing the card's name or synopsis on the board edits the scene. Attach and Detach
move text between the two. If the scene's summary and the card's synopsis are both
filled in and different, you're asked which one to keep; otherwise nothing is lost.

A scene belongs to at most one card. Attaching a scene that another card already
has is refused — detach it from that card first. If one scene serves several
story threads, keep one card and link it to a beat on each thread.

**Rearranging the board is planning, not editing.** Dragging a box saves only the
board's own layout, and dragging a card into a deck changes only the card's deck and
its place in story time — neither reorders your manuscript. The manuscript's reading
order is *shown* on the board (see **Layers**, below) so you can see plan against
draft, but the two only change when you tell them to (Write as scene, dragging a
written card's scene to another chapter, or editing the manuscript directly).

## Planning a card in a chapter

You can give an unwritten card a place in the manuscript before the scene exists.
Drag it by its grip onto a chapter's box and drop it where it belongs among the
chapter's cards; a bar shows where it will land. The card now reads **Planned**,
drawn with a dashed edge: it sits in that chapter, after the scene of the written
card before it, but it is still only a plan. It isn't in your manuscript and has no
scene.

- **It stays a plan until you write it.** Choose **Write as scene** on its ⋮ menu and
  the scene is created in that chapter, right after the scene the card was planned
  after. The card then reads **On the page** and shows the scene's title and summary.
- **Writing cards one after another keeps their order.** If you planned three cards
  in a row after the same scene, writing the first leaves the other two planned right
  after the new scene, still in the order you set. Write the next, and so on.
- **Move a plan** by dragging it again, to another place in the chapter, to another
  chapter, or back into a deck or **Loose cards** (which takes the plan away).
  **Undo** puts it back where it was planned, or where it came from.
- **Undo a Write as scene** deletes the new scene (you're asked first if it holds
  prose) and restores the plan, and the plans that had been moved after it.

A card that's already written can be dragged onto a chapter too. That is a real
move: its **scene** moves in the manuscript, into that chapter, next to the scene of
the written card before the drop (or before the first one, at the front). The same
works inside a chapter to reorder its scenes. **Undo** moves the scene back to its
old chapter and place.

## Decks

A **deck** is a plot-only box of cards — "Mara's backstory", "Ideas", "Act 3
options". It has a name and a short synopsis, but no scene and no place in the
manuscript: it's somewhere to keep cards that aren't part of the book yet.

- **Make one:** the toolbar's **New deck** puts a deck in view and opens its name
  for typing.
- **Drag cards in:** drag an unwritten card by its grip and drop it between two
  cards in a deck; a bar shows where it will land. It joins the deck and takes
  that place in story time. Drop it into **Loose cards** to take it out of its
  deck. A card that's **written** shows by its scene, so it can't be dragged into a
  deck — detach it first. Dropping a card onto a chapter is a different thing; see
  **Planning a card in a chapter**, below.
- **Deck menu (⋯):** **New card**, **New deck inside**, **Rename**, **Open** (the
  deck in its own editor: name, synopsis and its parent deck) and **Delete**. A
  deck from an ancestor project can be opened but not changed.
- **Nest decks:** **New deck inside** makes a child deck drawn inside its parent.
  To move an existing deck, **Open** it and set its **Deck** field in the rail.
  A card's own **Deck** field in its rail moves it between decks too.
- **Delete keeps the cards.** Deleting a deck removes only the box: its cards
  drop into **Loose cards** and its child decks move to the top level. You're
  asked first when it holds anything, and **Undo** brings the deck back with
  everything in it.

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

Causal links carry a check for you: if a link's *cause* happens **after** its
*effect* in **story time** (below) — the order things happen, not the order the
reader meets them — the link shows an amber **⚠** whose tooltip explains the problem,
and the effect card wears a **Cause is later** pill naming the cause. Telling a
cause late is ordinary craft and never flags; a cause that happens after its
effect is almost always a slip. It's a quiet nudge to reorder, not an error.

Causal links live on their own layer — turn them on with **Layers** (below).

## Story time

Every card has a place in **story time**: the order things *happen*, which is
separate from the order the reader is *told* them. A flashback can sit late in the
manuscript and still happen first in story time.

The toolbar's **Board | Story time** switch shows every card in one wrapping
sequence, earliest to latest. (The board remembers which view you last used.)

- **Drag** a card between two others; a bar shows where it will land. The left half
  of a card places the dragged card before it, the right half after it. Dragging
  changes only story time. It never moves a scene in the manuscript.
- **Earlier in story time** and **Later in story time** in a card's menu swap it
  with its neighbour, so dragging is never the only way. They hide at either end.
- **Place after…** opens a short list of your other cards (type to filter) and puts
  the card right after the one you pick.

Cards that come from an ancestor project read after your own cards and can't be
moved from here, or used as a place to drop. Moves can be undone with the board's
**Undo**.

## Layers

The **Layers** control toggles which relationships the board draws between cards:

- **Manuscript order** — the reading order of the draft.
- **Causal** — the "leads to" links you draw by hand.

Show one at a time to read the story a particular way, or combine them. To see
which cards share a beat, read the beat badges on the cards, or the count beside
each beat on its plotline.

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
**Cause comes later** warning, gathered up). If you've enabled AI and the plot-review prompt
is present, an **AI review** button offers a model's read of the plot — optional,
and only there when AI is on.

## Where to go next

- **[Custom fields](#guide:custom-fields)** — give cards and plotlines the fields
  your process needs.
- **[Views](#guide:views)** — the Templates shelf and every other list is a view
  you can shape.
- **[Getting started](#guide:getting-started)** — the wider tour, if you skipped
  ahead.
