# ADR-0080: A character arc is a plot subtype, not a plotline

- Status: **Accepted** — 2026-09-02 (Anton, in conversation). Trigger: dogfooding — a character-arc
  template (Positive Change Arc) instantiates into a node indistinguishable from a subplot, and
  Anton's read is that this *confuses* the writer rather than simplifying anything.
- Supersedes (in part): **ADR-0053**. Its unification of *plotline* and *template instance* into one
  node stands, and so does its shared beat mechanism — this ADR keeps both. What it overturns is
  ADR-0053's *universal* claim (§Context.1, §Why) that there is **no** difference between a plotline
  and an arc worth having: for a **character arc** there is one, and it is nameable.
- Amends: **ADR-0048** — plotting gains a second plot subtype; cards-over-manuscript, the container
  lock (#874), and the 0..n-cards-per-scene cardinality all **stand**.
- Follows: **ADR-0049** (built-in templates are a read-only ancestor layer — character-arc templates
  live there), **ADR-0030** (quiet writing desk — the new glyph and pill treatment answer to it),
  **ADR-0064** (a field type owns its display — the beat pill is where the subtype must read),
  and the class–instance model (`kind` = class, `entry_type` = subtype — the sanctioned extension
  point this ADR uses).

> **Verified against `2d22decb` (2026-09-02).** Roles, not call sites. `character_arc` is today only a
> `PlotTemplateFamily` label (`backend/app/models/plot.py`) discarded at instantiate; `plot:character_arc`
> does not exist yet; `beat_links` is the card→beat mechanism (`plot:card`, `default_schema.py`).

## Context

Since ADR-0053 there is **one** plot thread concept: a `plot:plotline` *is* a plot-template instance —
a named, coloured thread carrying a beat roster copied from a template. That unification was right for
what it addressed, and this ADR does not undo it.

But the built-in templates already come in two natures. Some are **story-structure** lenses (Three-Act,
Seven-Point, Thriller Escalation — `family: act|genre|…`). Others are **character-change** lenses
(Positive / Negative / Steadfast Change Arc, Story Circle — `family: character_arc`). The template's
`family` is the only thing that records which nature a template has — and **it is dropped at
instantiate**: a plotline made from Positive Change Arc keeps no marker, so it is indistinguishable
from a subplot. The node model captures **nothing** that says a thread is a character's arc, and no
plot node binds to a character at all.

ADR-0053 justified collapsing arc into plotline on a **user-comprehension** premise: *"a writer cannot
say what the difference between a plotline and an arc is."* At the time — when "arc" meant a *generic*
template instance — that was true, and collapsing it was correct. It is **false for a character arc**,
and the collapse now does the opposite of what it intended:

- A **plotline** is an *external* thread — a sequence of events, authored as cards. Its beats are things
  that *happen*.
- A **character arc** is an *internal* trajectory — how one character's belief or behaviour *changes*.
  Its beats are *states* of a person, and they are realised *through* the plot's events, not events in
  their own right.

The relationship between them is **cause → effect**, not two parallel threads: the events on a plotline
*cause* the change an arc tracks. A writer can say that difference readily, and bundling the two into
one UI — one palette, one node shape, one undifferentiated beat pill — is what makes the board confusing.
So the premise ADR-0053 rested on is inverted here, on the exact axis it claimed: user comprehension.

## Decision

### 1. A character arc is a plot subtype — a sibling of the plotline under a shared beat-holder base

The plot kind gains an abstract base, **`plot:thread`** (internal, never instantiated — like
`plot:base`), carrying the **beat-holder contract**: the instantiated beat roster (`instance_beats`)
and the template lineage (`source_template_*`) a plotline holds today. Its two concrete children are:

```
plot:base
└─ plot:thread             abstract: instance_beats + source_template lineage (the beat-holder contract)
   ├─ plot:plotline        + colour; can be a card's primary thread
   └─ plot:character_arc   + character binding (§2); never primary (§4)
```

They are **siblings**, not parent-and-child: a character arc is **not** an `is_a` plotline. That is the
whole thesis, and the *type* must say it — otherwise "an arc is a kind of plotline" leaks straight back
in (it would satisfy every `plot:plotline` target and filter; see §4, §6). What the two **share** — the
beat mechanism — lives in the **common ancestor**, not in one inheriting from the other, so
`plot:character_arc` reuses that machinery without re-declaring it and without becoming a plotline. It
carries **its own glyph**, so the writer meets it as a distinct object everywhere it appears. This is
the sanctioned class–instance extension point (a new subtype under an existing kind), not a new subsystem.

This is **not** a revival of the generic "arc" (`plot:template_instance`) that ADR-0053 retired — that
one genuinely was a plotline by another name. The character binding (§2) is the discriminator it lacked.

### 2. A character arc binds to a character — that binding is what makes it an arc

A `plot:character_arc` names the character it is about: an `entity_ref → lore:character`. This is the
arc's defining reference — an arc *about no one* is not an arc, it is a plotline. A plotline has no
such field. The binding is what a writer points at to answer *"whose change is this?"*, and it is what
lets one pivotal card show that it changed **this** character (§5).

### 3. The mechanism is shared; the meaning is read off the holder (preserves ADR-0053)

Both subtypes are **beat-holders** (they share the `plot:thread` base, §1), and a card links to a beat
through the **one** existing gesture — `beat_links` (ADR-0053 §4): drag a beat off a thread node onto a
story card. This ADR does **not** fork that mechanism. The link targets the `plot:thread` base, so it
accepts either subtype as a holder, and reads the link's **meaning** off which subtype the beat belongs to:

- beat's holder is a **plotline** → the link means *"this card **is** this beat"* (the event happens here);
- beat's holder is a **character arc** → the same link means *"this card **causes** this change."*

Keeping one mechanism and two meanings is the load-bearing move: it is why this is a subtype and not a
bespoke arc subsystem. The terms for the two are an **event-beat** (on a plotline) and a **change-beat**
(on a character arc).

### 4. A character arc is never a card's primary/colour thread — only a beat-fulfilment target

ADR-0053 §5 stands: a card's **primary plotline** owns its tint/stripe (the colour axis), and a card
already has one spatial home (its manuscript container, #874). A character arc takes **neither**. It is
only ever a *fulfilment target* — cards link to its change-beats; a card's primary thread is always an
event-plotline. This is a functional difference from a plotline (which *can* be primary), and part of
why the subtype is not a mode flag. Because an arc is **not** an `is_a` plotline (§1), the card's
primary-plotline reference — which targets `plot:plotline` — excludes arcs *by type*: the invariant is
enforced by the schema, not policed in the UI.

### 5. Beat pills on a card are visually distinct by subtype and by character

Because one card can carry both event-beats and change-beats, the pills must read **at a glance** as
different kinds, or the card lies about what its markers mean. Plotline already owns **colour** (§4), so
the arc distinction rides a **different channel**: the character-arc **glyph** (§1) on the pill, plus the
**bound character's** identity (§2) — so a pivotal card that turns two characters shows two
character-attributed change-pills, not two identical "arc" chips. The pill row **segments** event-pills
from change-pills rather than interleaving them. Any new colour or treatment comes from design tokens,
per ADR-0030 and the style-token guard — not literals.

> **Amended by Amendment 1 (2026-09-03):** the "different channel, *not a recolour*" clause is superseded —
> an arc **does** carry colour (its bound character's, overridable); the **glyph** is the discriminator, not
> the absence of colour. §4's "takes neither [colour]" is likewise narrowed to the *card's* stripe. See
> Amendment 1 below.

### 6. Share the mechanism, deliberately not the UI surface

The shared beat machinery (§3) will tempt a *"these are so similar, use one pane"* re-collapse — the same
pull that produced ADR-0053, from the other side. The discipline this ADR sets: the mechanism is shared;
the **presentation is not**. Concretely, character-arc templates are **separated from plotline
(story-structure) templates in both surfaces that list them — the Library template list (ADR-0049) and
the board's instantiation palette (ADR-0053 §2)** — keyed on the template's `family` (§7). The writer
picks *"a character arc"* or *"a plotline"* as a distinct act, never fishes an arc out of one flat list
of threads. A character arc also carries its own glyph, its own character picker, and its own change-beats,
and is **not** bundled into the plotline's editor. This is the inverse of the usual "don't special-case":
the special-casing here is the *identity*, and it must stay visible even though the plumbing is common.

### 7. Instantiation selects the subtype from the template's family

Instantiating a template whose `family` is `character_arc` spawns a **`plot:character_arc`**; any other
family spawns a `plot:plotline`. This replaces the current behaviour, where `family` is discarded at
instantiate and every template yields a plotline. The template files themselves do not change — only what
they spawn does.

## Why / rejected alternatives

- **Leave arcs collapsed into plotline (ADR-0053 status quo).** Rejected — the user-comprehension premise
  that justified the collapse is inverted for character arcs; bundling them now *creates* the confusion it
  meant to remove.
- **A `family` / `is_arc` flag on `plot:plotline` instead of a subtype.** Rejected — a character arc has a
  *required* character binding a plotline lacks, and is *never* a card's primary thread while a plotline
  can be. Those are functional differences, so a node that behaves one way when the flag is set and another
  when it isn't is the "mode is presentation, not functionality" latent-bug shape. A subtype states the
  difference in the type, where it belongs.
- **Beats as their own nodes.** Still rejected (ADR-0053 §Why) — a change-beat is a row inside its arc node,
  dragged onto cards, exactly as a plotline's beats are. No new need is demonstrated.
- **A per-character swimlane / track on the board.** Not rejected — **deferred** (see Open). Note only that
  ADR-0053's reason for rejecting *plotline* lanes (a card serves several threads, so it cannot live in one
  lane) does **not** transfer to an arc *beat*-track: a character's change-beats have a single home (their
  arc = their character), so a track of beats is not a lane of cards. That makes a character track
  *permissible* where a plotline lane was not — it does not make it *decided*.

## Consequences

- **The schema gains an abstract base (`plot:thread`) and one concrete entry_type (`plot:character_arc`)
  plus one glyph**, and `plot:plotline`'s parent moves from `plot:base` to `plot:thread`. All **additive**:
  existing `plot:plotline` nodes are untouched, `plotline is_a plot:base` still holds transitively, and the
  shared `instance_beats` / `source_template_*` fields move up to `plot:thread` (inherited by both
  children, not re-declared).
- **No migration reclassifies existing threads.** Which existing plotlines "are really" character arcs is
  not recoverable: the source template's `family` was dropped at instantiate and is not on the instance.
  So existing plotlines stay plotlines; a writer authors a character arc fresh. There is no storage-shape
  change to owed a DocumentMigration (ADR-0071) — the change is a new subtype, merged from the default
  schema like any built-in entry_type.
- **`beat_links` generalises its target** from "a plotline + beat" to "a `plot:thread` beat-holder
  (plotline or arc) + beat." The card fields are unchanged; the plot-local healer accepts an arc node as a
  valid holder.
- **The card's marker story grows** from "event-beat badges" to "event-beat and change-beat pills,
  segmented and distinctly styled" (§5).
- **The template list and the board palette separate arcs from plotlines.** ADR-0053 replaced the Arcs and
  Plotlines rails with one template palette; this ADR keeps one palette but **sections it** — character-arc
  templates apart from story-structure templates — and the Library template list (ADR-0049) does the same.
  The split is keyed on `family` (§7); its exact chrome (two sections, a filter, a tab) is mockup detail.
- **The AI already reads a thread's beats and premise** for the plot diagnostic; a character arc reaches it
  as a character's change-track bound to a named character — richer context, on the existing path, with no
  new transport.

## Non-goals

- **Reworking the plotline.** `plot:plotline` is unchanged; this adds a sibling.
- **The character-track / spine view** — deferred (Open), not designed here.
- **Beats-as-nodes, a lanes-and-columns grid, reworking the #874 container lock or the 0..n-cards-per-scene
  cardinality.** All out of scope (ADR-0048 / ADR-0053 non-goals stand).
- **A "convert this plotline into a character arc" affordance.** Not part of this ADR; if a workflow demands
  it later, it is its own decision.

## Open — to settle at implementation / mockup

These are recorded as *out of scope for now*; this ADR deliberately does not sketch their shape (a deferred
sketch acquires authority it has not earned).

- **The character-arc reading of the board.** Two questions a writer asks — *"where in the plot does this
  character change?"* and *"what is the shape of this transformation?"* — are two views of the one model
  (a character's ordered change-beats, each caused by cards). The first is a character **filter/highlight**
  over the existing board (it reuses the ADR-0053 §6 focus mechanism); the second is a dedicated character
  **track**. Ship the filter first; a track is a later addition, gated on the filter proving too flat in
  use — not designed in this ADR.
- **When the character binding is captured** — at instantiate (a picker fires) or bound afterward on the
  arc node. The *invariant* (an arc names its character) is decided; the *timing/UX* is not.
- **The pill's exact rendering** — the *channel* is decided (glyph + character identity, not colour); the
  specific mark, and how the row segments and counts overflow across the two pill kinds, are mockup detail.
- **The chrome of the arc/plotline separation** in the template list and the palette — *that* they are
  separated is decided (§6); whether it reads as two sections, a filter, or a tab is mockup detail.

## User journeys (definition of done)

- **Create an arc.** Writer opens the palette's **character-arc** section, instantiates "Positive Change
  Arc" → a `plot:character_arc` node appears with the arc glyph and its change-beats → binds it to *Alice*.
- **Mark a cause.** Writer drags the arc's "accepts the hard truth" change-beat onto the climax card → the
  card wears a change-pill (arc glyph + *Alice*), visibly distinct from that card's plotline event-pills →
  the beat's use-count ticks.
- **Read a pivotal card at a glance.** The card that resolves the heist *and* turns Alice *and* breaks Bob
  shows one event-pill and two character-attributed change-pills, segmented — the writer sees three
  different jobs the card does without opening it.
- **The two never blur.** Nowhere does the writer meet a control that is ambiguous between "this card is an
  event" and "this card causes a change" — the glyph and the character say which every time.

## Test surface

- **Model:** a `plot:character_arc` resolves as a plot subtype, carries change-beats, and names a
  `lore:character`; a `plot:plotline` still cannot name one; an arc is never a card's primary plotline.
- **Type:** `plot:character_arc` `is_a` `plot:thread` and `plot:base`, but is **not** `is_a`
  `plot:plotline`; the card's primary-plotline ref rejects an arc by type; both subtypes inherit
  `instance_beats` / `source_template_*` from `plot:thread`.
- **Instantiation:** a `family: character_arc` template spawns a `plot:character_arc`; a `family: act`
  template spawns a `plot:plotline`; no existing plotline is silently reclassified.
- **Mechanism:** a card's `beat_links` accepts an arc node as a holder; a change-beat's use-count equals
  the live cards linking it, and drops on unlink/delete — the same contract plotline beats already have.
- **Presentation (in-app; SvelteFlow not headless-testable):** a card carrying both an event-beat and a
  change-beat renders two distinct, segmented pill kinds; a card causing two characters' changes shows two
  character-attributed change-pills.

## Amendment 1 — arcs carry colour (2026-09-03)

Dogfooding the slice-3 mockup surfaced an error in **§5** (and the colour clause of **§4**). §5 said the
arc distinction rides glyph + character **"not a recolour"**, and §4 that an arc **"takes neither"** colour.
That framing is wrong: nothing rendered on a screen is colourless — an "arc with no colour" is just an arc
coloured by omission. The real question is **which** colour, not **whether**. Revised:

1. **An arc has colour.** Its default is its **bound character's** resolved colour (the normal resolver:
   instance override → type → the `lore`/character kind default), and the arc **keeps its own colour
   picker** to override — an optional `color` field, exactly as a plotline has one. So colour answers
   **"whose change"** for an arc as it answers **"which plotline"** for a plotline.
2. **Colour is not the discriminator** between the two subtypes — the **seedling glyph** (vs the plotline's
   icon), the `Character arc` type tag, and the character-binding row are. That is *why* colour is free to
   carry "which / whose" on both without the two colliding: the glyph already tells the reader the kind.
   (This is the correction to §5's "different channel, not a recolour": the *distinguishing* channel is the
   glyph, but colour is still present, re-referented to the character.)
3. **§4 holds where it matters.** A *card's* stripe/tint — its one colour axis — still comes from its
   **primary plotline**, never an arc; an arc is still never a card's primary/colour thread. What Amendment 1
   changes is only that the arc **node** and its **change-pills** are themselves character-coloured.
4. **Change-pill treatment (settles §5's "mockup detail").** An event-pill = plotline colour + a dot; a
   change-pill = character colour + the seedling + the bound character's **single-letter avatar** + label
   (single letters suffice — a story has few change arcs). The pill row **segments** `Events` from `Changes`,
   and a segment's label shows **only when that segment has a pill** (no divider between the synopsis and the
   first segment).
5. **Board layout (extends §6 to the canvas).** Plotline holder-nodes and arc holder-nodes render in
   **separate bands** on the board — the same arc/plotline separation §6 applied to the template list, now
   applied to the on-canvas holder layout.

Delivery: **3a** (backend — the arc `color` field, arc HTTP routes, and the board projection widened to
enumerate arcs and carry per-beat holder-subtype + character) then **3b** (frontend — the arc board node in
its own band, the change-pill treatment above, the character + colour pickers, and closing the
instantiate-an-arc dead-end the type split left).

## Amendment 2 — arc reasoning is a transformation + causation lens (2026-09-03)

The Consequences noted that an arc reaches the AI "as a character's change-track bound to a named character
— richer context, on the existing path." That is the *data* (delivered as the `<character_arc>` element in
the plot-context). This amendment records the *reasoning* the AI does with it, which the plotline prompts do
not already cover.

A plotline prompt reasons about **event structure** — is the beat sequence complete, where are the gaps,
what pays off out of order. A character arc needs a different read on two axes, and neither is expressible as
"a plotline with different beats":

1. **Transformation coherence.** The question of an arc is not *is the sequence complete* but *is the change
   earned* — the want and the lie shaping it, pressure the old belief cannot solve, the truth glimpsed, the
   lie made costly, the choice from the changed belief, the changed self shown in action. This vocabulary is
   the arc template's own (`ai_use_guidance` / `global_diagnostic_questions` / `common_weak_spots`), and it
   already reaches the model per-arc through `<character_arc>`'s `use_guidance` / `diagnostic_questions` /
   `weak_spots`. The prompt's job is to tell the model to *read in that register* — transformation, not
   sequence — and to use each arc's carried guidance.

2. **Causation, which is inherently cross-thread.** An arc's change is *earned by the plotline events that
   cause it* — the ADR's own cause→effect thesis (§Context, "a character arc = the change those events
   cause"). The board already expresses this in the data: a single card can fulfil **both** a plotline
   event-beat and an arc change-beat, and the card's rendered `<fulfils>` shows both. So the causal evidence
   is legible — a change-beat fulfilled by a card that *also* advances an external event is earned; a
   change-beat **no card fulfils** is a change the prose asserts but never dramatizes; a change that lands
   *before* the events that would cause it is unearned.

**This lives across the existing plot prompts, not in a new subsystem.** Because causation is cross-thread,
a siloed arc-only diagnostic would be blind to what earns the change — so the *whole-board* diagnostic is
where the arc read belongs. Three surfaces, all user-authorable `.md` under `builtin_library/prompts/` (the
diagnose-plot / revise-per-family split already exists):

- **`diagnose-plot.md` gains an arc section** — the whole-board diagnostic reads arcs alongside the
  plotlines and cards that cause their changes; it judges each arc as earned-by-causation and groups arc
  findings under the character.
- **A new `revise-character-arc.md`** — the missing sibling to `revise-plotline.md` (`offer_on:
  plot:character_arc`, the same extract-to-node commit loop and field machinery), carrying the deep
  single-arc transformation lens toward a committable change-beat roster and description.
- **`revise-plot-card.md` gains an arc-advancement read** — a card can advance both an event and a change,
  so a card revision asks whether this card moves the want→need / tests the lie for any arc it touches, and
  whether that change is earned by what the card actually dramatizes. (This also corrects the paragraph's
  pre-ADR-0080 loose use of "arcs" for plotlines.)

**Anti-goals.** No invented psychology the board does not show — the arc prompts hold the same discipline the
plotline prompts already state ("never invent cards, beats, or events that aren't there"); reason from the
cards, beats, and causation the board carries. And no separate arc-reasoning machinery — same plot-context,
same commit loop, same teaching-artifact standard (a reader learns the arc read by copying these, and
`revise-character-arc.md` stands as the worked sibling to `revise-plotline.md`).

Delivery: one slice — the `diagnose-plot.md` arc section, the new `revise-character-arc.md`, and the
`revise-plot-card.md` update, with tests that the arc reasoning renders and the new prompt ships and routes.
No model or transport change (Amendment-2 is prompt prose over the data Amendment-1's delivery already
carries).
