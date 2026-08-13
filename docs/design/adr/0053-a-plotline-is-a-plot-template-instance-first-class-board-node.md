# ADR-0053: A plotline is a plot-template instance — a first-class board node

- Status: **Accepted** — 2026-08-13 (Anton, PR #880). Framed with Anton in conversation after the container-lock work (#874)
  exposed how thin the plotline concept had become. His diagnosis: master's terminology streamlining
  **severed two things that were always one**, and the board should say so. This ADR unifies them and makes
  the result a real board node — which, as a free consequence, makes the whole board undoable (subsuming the
  parked ADR-0052).
- Feature: **#875** (undo everywhere) is the trigger; this ADR is the model it lands on.
- Amends: **ADR-0048** §2 (a plotline was "a name, a color, a description" that cards merely reference) and
  its template-instance/arc split. Cards-over-manuscript, the 0..n-cards-per-scene cardinality, and the
  soft manuscript-container layout (#874) all **stand** — this changes only what a plotline *is*.
- Supersedes: **ADR-0052** (plot-board content-op undo) — its command-pattern design is correct and is
  folded in here (§7); once every plotline op is a board-node command, the separate-editor-surface problem
  ADR-0052 wrestled with disappears, so it does not need its own ADR.
- Follows: **ADR-0050** (the shared caretaker + self-reporting commands — this is its §8 *slice 2*),
  **ADR-0049** (the Library as a read-only ancestor layer — where built-in templates live and where
  roll-your-own clones from), **ADR-0038 §A** (nodes edit in place on the canvas), **ADR-0030** (quiet
  writing desk).
- Historical note: `origin/plotting`'s `PlotLine` carried a `template_instance_id` and auto-created a
  plotline when a template was applied — the link this ADR restores, then goes past by making the plotline
  *be* the instance rather than pointing at it.

> **Verified against `d557379` (2026-08-13).** Roles and behaviours, not call sites. Claims about *current*
> master (the rails, #863 card tint, #871 badge tint) describe what this ADR supersedes.

## Context

On master the plot board has **two separate first-class node kinds that both group cards and neither of
which fully earns its place**:

- a **plotline** (`plot:plotline`): name + colour + description; a card references one as its primary
  plotline; renders as the card's tint/stripe (#863). It carries no beats and no structure — so it reads as
  "just a colour."
- an **arc / template instance** (`plot:template_instance`): an instantiation of a diagnostic template
  (Three-Act, Hero's Journey…); carries the beat roster; lives in the **Arcs rail** and opens in its own
  **editor pane**; cards fulfil its beats via drag-linked badges (#824, tinted by arc colour #871).

The archaeology settles that this split is an artefact, not a design: `origin/plotting` had **one** board
object, `PlotLine`, with an optional `template_instance_id`, and *applying a template auto-created a
plotline bound to it*. Master pulled them apart and, in doing so, left the plotline as a bare colour and put
all the structure in a second concept the user meets through two different rails and a document editor.

Two problems compound:

1. **The concept is confusing.** A writer cannot say what the difference between "a plotline" and "an arc"
   is, because there isn't one worth having.
2. **Undo cannot cover it cleanly.** ADR-0052 found that arc edits happen in a *separate editor pane*, a
   different undo surface from the board — so "undo everything" fractured across surfaces.

Both dissolve if a plotline and a template instance are **the same node, and that node lives on the board.**

## Decision

### 1. A plotline *is* a plot-template instance — one node kind

There is one concept: a **plotline**. It is an **instance of a plot template** — a named, coloured thread
that carries an ordered list of **beats** (copied from the template at instantiation, then editable
per-instance). "Arc" and "template instance" are retired as user-facing terms and as separate node kinds;
the master `plot:plotline` (name+colour) becomes the **empty/ad-hoc** case (§2). A plotline answers *"which
thread — and, if it has beats, against which structure?"* in one object.

### 2. Plot templates are a palette; instantiating one spawns a plotline node

The board carries a **template palette**, replacing both the Arcs rail and the Plotlines rail. It lists:

- the **built-in** templates (the ADR-0049 Library tenant — Three-Act, Hero's Journey, …),
- the writer's **own** templates, authored via a **`+ New template`** (roll-your-own — an ADR-0049
  clone/create, so a template is an ordinary owned node), and
- one **Empty** tile — instantiating it makes an **ad-hoc plotline** with no preset beats (a free thread the
  writer beats-out by hand).

Dragging a palette tile onto the board (or clicking it) **instantiates a plotline node**. The palette is
potential; the node is the instance.

### 3. A plotline is a first-class board node, holding its beats, edited in place

A plotline is a Svelte-Flow node on the board (like a card), **holding its beat list**, and **edited in
place** (ADR-0038 §A — the selected node expands and you edit on it): rename, recolour (swatch row),
add / remove / reorder beats, per-beat text, guidance. **There is no separate arc editor pane** — the
document-pane editing of a template instance is retired into the node. This is the move that makes undo whole
(§7): every plotline edit is a board gesture on one surface.

### 4. Beats are assigned by dragging from a plotline node onto a story card; a card may carry several plotlines' beats

Assignment is the #824 gesture, now sourced from the node: **drag a beat off a plotline node onto a story
card**. The card then shows that beat as a badge tinted by the plotline's colour (#871), and the card is
**dragged in its manuscript box, or free on the board** — the beat comes to the card, the card does not move
to the plotline. A card **may fulfil beats from several plotlines at once** (drawn in the mockup: one card
wears a Main-plot beat and a Romance beat). The card keeps a **primary plotline** for its own tint/stripe
(#863 stands, following the primary); the per-beat badges (#871) carry each beat's own plotline colour. So
one card can visibly belong to its primary thread while contributing to others.

### 5. Two orthogonal axes, one spatial home; arrangement is free

The board keeps **two axes that must not fight for the same spatial slot**: a card's **manuscript container**
(act/chapter — its spatial home, locked by #874) and its **plotline(s)** (the colour + beats axis). A
plotline node is **not** a container cards sit in; it is a node you drag beats from. **Everything is
freely draggable** — cards within their box (#874), plotline nodes anywhere — so the writer arranges the
board as they like (a columnar default is a starting layout, not a constraint). Plotline nodes carry a
position in the board `layout` like cards do.

### 6. A beat shows its use-count; a plotline has a "focus" toggle that lights the thread

Two affordances make the diagnostic real — the payoff neither `origin/plotting` nor master built:

- **Use-count on every beat.** Each beat on a plotline node shows **how many cards fulfil it**. A `0` is a
  gap the structure exposes; a high count is an over-loaded beat. This is what a template *is for* — the
  board answers "does the draft satisfy this structure?" at a glance.
- **Per-plotline "focus" toggle.** Toggling a plotline into **focus** lights up a **highly visible set of
  edges** — the chain of cards that fulfil that plotline's beats, in reveal/beat order — so the writer can
  **isolate one thread across the whole book**. This is ADR-0048 §2's promised "see the threads" /
  highlight-by-plotline, finally given a home; it is what makes a plotline earn its keep beyond colour. Only
  the focused plotline's chain is emphasised; the rest recede.

### 7. Undo folds in: every plotline and card op is a board-node command (supersedes ADR-0052)

Because a plotline is now a board node and its editing is on-canvas, **every content op on the board is a
command on the board's own caretaker** (ADR-0050 §8 slice 2) — there is no second surface to reconcile. This
is the whole of "undo everything," and it subsumes ADR-0052:

- **Node create/delete** — `Create(id, content)` / `Delete(id, content)` for cards **and** plotlines;
  instantiating from the palette, seeding, deleting. Undo/redo call the **backend inverse**, so the
  caretaker gains **async-command support** (await + a `busy` gate so mashed Ctrl+Z can't race two inverse
  calls); it stays domain-agnostic. The command **carries the id** (ADR-0050 §6), so nothing re-mints an
  identity and no ref dangles — the one backend affordance needed is **create-with-a-supplied-id** (restore,
  collision-rejected), for cards and plotlines alike.
- **Field/beat edits** — rename, recolour, add/remove/reorder a plotline's beats, edit a card's synopsis,
  reassign primary plotline, link/unlink a beat to a card: `FieldEdit(id, field, before, after)`. All
  on-board now, all recorded.
- **Realize** still mints a **scene file**; its undo detaches and **deletes the scene only when the card is
  its sole referent** (0..n cards per scene), behind a **suppressible confirm** naming the scene + its
  snapshot count (ADR-0043; `dontShowAgainKey`). Redo re-mints.
- **Multi-command gestures** (seed, realize) group as one undo step via ADR-0050 §4's implicit shared-id
  transaction.
- The **keyboard-reach fix** lands here too: cards are `selectable:false`, so Ctrl+Z never focuses the
  board — `tabindex="-1"` on `.plot-board` + focus on pointerdown/dragstop.

The layout-only "Undo layout" control becomes a plain "Undo" over the whole board.

## Why / rejected alternatives

- **Keep plotline and arc as two concepts (master today).** Rejected — the split is what makes the plotline
  read as decoration and fractures undo across surfaces; no user can name the difference.
- **Keep them separate but re-link (origin/plotting's `template_instance_id`).** Rejected as half-measure —
  a plotline *pointing at* an instance still leaves two nodes, two rails, and the editor-pane surface. Making
  the plotline *be* the instance is simpler and is what makes it a board node.
- **Whole-state / scene-file snapshots for undo.** Rejected (again) — ADR-0050 §Why and Anton's standing
  call: the id-carrying command has no id-conflict, snapshots clobber concurrent edits and fight the
  file-based model. The command pattern is settled.
- **Plotline as a swimlane / container the cards sit in.** Rejected — a card already has one spatial home
  (its manuscript box, #874); a card fulfils *several* plotlines' beats, so a plotline cannot own the card's
  position. Plotline is the drag-source + colour axis, not a lane. (`origin/plotting` never used plotline
  swimlanes either — its lanes were always manuscript structure.)
- **Beats as their own nodes.** Rejected for v1 — a beat is a row inside its plotline node (dragged onto
  cards); promoting beats to nodes multiplies the canvas without a demonstrated need. Reconsider only if a
  beat needs its own position/edges.

## Consequences

- **Terminology and data model unify.** One kind (a plotline = a template instance). The master
  `plot:template_instance` and `plot:plotline` collapse; the ad-hoc case is the empty-template instance.
  Pre-1.0, this is a **recreate, not a migration** (`feedback_no_pre_1_0_migrations` — no migration code,
  test projects rebuilt).
- **The Arcs rail (#737/#863) and Plotlines rail (#737) are retired**, replaced by the template palette; the
  template-instance **editor pane** is retired into on-node editing. The `+ New template` reuses ADR-0049
  clone/create.
- **Undo covers the whole board** with no new ADR beyond this; the caretaker gains async commands + a busy
  gate; the cards endpoint gains create-with-supplied-id. ADR-0052 is withdrawn (folded in here).
- **The card's colour story** shifts from "one plotline tint" to "primary-plotline tint + per-beat
  plotline-coloured badges" — #863 and #871 both stand, composed (§4).
- **A plotline earns its keep** via use-counts + focus mode (§6) — the "see the threads" payoff ADR-0048 §2
  promised.
- The board gains a **second draggable, persisted node type** (plotline nodes carry a `layout` position like
  cards).

## Non-goals

- **Undoing prose edits inside a scene.** TipTap owns that; realize/detach/delete of the scene are board ops.
- **Cross-pane / app-wide undo, and persistent-across-reload undo.** Board-scoped, in-session (ADR-0050 §3/§5).
- **Reworking the #874 container lock or the 0..n-cards-per-scene cardinality.** Both stand.
- **Beats-as-nodes, book-level plotline registry, a lanes-and-columns grid.** Out of scope (§Why /
  ADR-0048's own non-goals).

## Open — to settle at implementation / mockup

- **Where plotline nodes sit by default** — a bottom band, a side lane, or scattered free. Arrangement is
  free (§5); only the *initial* placement needs a sensible default (0005's lesson: commit to free-drag, not
  to a pixel home).
- **Focus-mode edge rendering** — SvelteFlow has no node-avoiding router; the focused chain likely reuses
  the existing beat-sequence edge layer with a prominent style. Confirm it reads clearly across containers.
- **Primary-plotline selection** — is a card's primary the first beat dragged on, or an explicit pick? (§4
  keeps a primary for the tint; how it's chosen is UX detail.)
- **Palette placement** — a rail vs a menu; the ADR commits to *a* palette with `+ New template` and an
  Empty tile, not its chrome.

## User journeys (definition of done)

- **Instantiate.** Writer drags "Three-Act" from the palette → a plotline node appears holding 7 beats,
  each showing a `0` use-count → drags "Setup" onto a card → the card wears a Setup badge and the beat's
  count ticks to `1`.
- **Roll your own.** Writer clicks `+ New template`, authors "Heist beats" → it appears in the palette →
  instantiates it as the "The Heist" plotline.
- **Ad-hoc.** Writer instantiates the Empty tile → a coloured "Grandpa's secret" plotline with no beats →
  adds beats by hand as the subplot takes shape.
- **See the thread.** Writer toggles the Romance plotline into **focus** → a bright chain lights the cards
  that fulfil its beats, in order, the rest of the board receding → toggles off.
- **Undo everything.** Writer seeds 40 cards → Ctrl+Z removes all 40 in one step; deletes a plotline →
  Ctrl+Z restores it with its beats and every card badge that pointed at it; realizes a card → Ctrl+Z warns
  and (confirmed) deletes the minted scene.

## Test surface

- **Model:** a plotline node carries beats + colour + source-template ref; the empty case has no beats; a
  card records beat-links across multiple plotlines and one primary.
- **Use-count:** a beat's count equals the number of live cards linking it; drops when a card unlinks or is
  deleted.
- **Undo (per ADR-0052, folded):** create/delete/field round-trips carry the id and refs; realize-undo
  cardinality (sole-referent scene deleted, shared scene only detached); async busy-gate serialises mashed
  Ctrl+Z; keyboard reach after a mouse gesture.
- **Focus mode (in-app; SvelteFlow not headless-testable):** toggling a plotline emphasises exactly its
  card-chain and recedes the rest.
