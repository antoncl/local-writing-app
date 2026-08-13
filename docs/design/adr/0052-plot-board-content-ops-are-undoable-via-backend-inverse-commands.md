# ADR-0052: Plot-board content ops are undoable via backend-inverse commands

- Status: **Proposed** — 2026-08-13. Undo on the plot board is layout-only today (drags), a deliberate
  code-level stance ("content ops are intentful mutations OUTSIDE the caretaker"). Anton's call: that is
  wrong — **undo means undo everything**. A writer who seeds, adds, deletes, or realizes and presses
  Ctrl+Z expects it reversed. This ADR is the design he asked for before code.
- Feature: **#875** (plot board: undo/redo should cover content ops, not just layout).
- Follows: **ADR-0050** (the shared caretaker + self-reporting command protocol — this is its §8 *slice 2*,
  "the second surface reuses the caretaker with its own command vocabulary", now designed). **ADR-0048**
  §S13 deferred plot-board undo ("to be re-judged against single-commit writes plus snapshots") — this
  ADR **settles that deferral**, in favour of commands and against snapshots.
- Relates: **ADR-0043/0044** (scene snapshots — a scene is a deletion unit with its snapshots; the
  rejected snapshot-undo alternative). **ADR-0042** (the confirm + `dontShowAgainKey` precedent for a
  destructive, irreversible-feeling gesture).

> **Verified against `7bd343a` (2026-08-13).** Roles and behaviours, not call sites; symbols named before
> locations. A later reader who finds the code disagreeing should treat the ADR as aged, not the code as wrong.

## Context

The plot board (ADR-0048) is a SvelteFlow canvas (`PlotEditor.svelte`) over a projection of `plot:card`
nodes. Two classes of edit happen on it:

- **Layout** — dragging a card. Held in `Node.position`, persisted to the board's opaque `layout` dict.
  Already undoable: `PlotEditor` mounts a `GraphUndoController` (ADR-0050) and records **one
  `moveNodesCommand` per drag**. The control is even labelled "Undo **layout**".
- **Content** — create card, seed-from-manuscript, delete card, rename, edit synopsis, reassign plotline,
  set page-status, link/unlink a beat, link/unlink a causal edge, realize a scene, detach a scene. Each is
  an **intentful backend mutation**: a store helper in `lib/stores/plotBoard.ts` calls an endpoint and
  refetches the projection. **None is recorded** — they are fire-and-forget, deliberately kept out of the
  caretaker.

That deliberate stance has two sources. ADR-0048 §S13 listed undo as a *future issue*, "to be re-judged
against single-commit writes plus **snapshots**". And the plot-board code adopted, as an interim, "an
in-memory undo must never reverse a scene mint" — because realizing a card mints a **scene file** (and a
naive in-memory undo cannot un-write a file). Neither is an accepted ADR decision that content ops are
*unundoable in principle*; both are a deferral. This ADR ends the deferral.

Anton found the gap live: seeding twice and pressing Ctrl+Z, the buffer stayed empty (correct for
layout-only undo, surprising for a writer). His principle is flat: **everything should be undo/redo-able.**

Two facts set the design.

1. **ADR-0050 already anticipated this exact surface.** Its §8 slice 2 is "the plot board mounts the same
   caretaker and defines its own command vocabulary — named, not designed there." Its §6 already fixes the
   invariant a create/delete pair needs: **a recreated node returns with its same id**. So the mechanism
   exists; this ADR supplies the vocabulary.
2. **The snapshot vs command debate is settled — command pattern.** ADR-0050 §Why rejected whole-state
   snapshots (they hard-code undo to one surface's state shape and bury "what is one change" in a central
   diff). ADR-0048 §S13 floated snapshots again as the open question. It is closed here the same way, and
   Anton's id point removes the only friction: a `Delete(id)` conflict does not exist because **the command
   carries the id** — undo recreates *that* id, redo deletes *that* id, no new identity is ever minted.

## Decision

### 1. Content ops become commands on the board's own caretaker (ADR-0050 §8 slice 2)

Each board content op **records a labelled reversible command** on the `GraphUndoController` the board
already owns, instead of firing and forgetting. The caretaker is unchanged (§2 of ADR-0050: it knows only
commands + transaction ids). The board defines the command vocabulary. The "Undo **layout**" label becomes
"Undo" — it now covers the whole board.

### 2. A plot-board command reverses a **backend mutation**, not an in-memory array — so undo/redo are async

This is the one real extension beyond ADR-0050, whose view-designer commands mutate rune arrays in memory
(autosave persists later, "no server round-trip for the restore itself"). A plot-board content op **is** a
server mutation, so its command's `undo()`/`redo()` **call the inverse endpoint and refetch the
projection**. Consequences that must be designed, not discovered:

- **`undo()`/`redo()` return promises.** The caretaker invokes them and must **await** before accepting the
  next, and the undo/redo controls + Ctrl+Z are **gated while a command is in flight** (a `busy` state), so
  a mashed Ctrl+Z cannot overlap two inverse calls into a race. This is the minimal caretaker addition; it
  stays domain-agnostic (it awaits an opaque promise, still knowing nothing about cards).
- **Undo is a real persisted edit** (unlike layout undo, which rode autosave). There is no separate
  autosave step for content undo — the inverse call *is* the persistence.
- **Failure is surfaced, not swallowed.** If an inverse call fails (e.g. a 409), the command does not
  advance the cursor and the board reports it (reuse the #756 board error surface). The in-flight state
  reconciles by refetch.

### 3. The command vocabulary

| Op | command (undo ⇄ redo) |
|---|---|
| create card, add card | `CreateCard(id, content)` — undo `delete(id)`, redo `create(id, content)` |
| seed-from-manuscript | one **transaction** of `CreateCard` per created card (seed returns the ids) |
| delete card | `DeleteCard(id, content)` — undo `create(id, content)`, redo `delete(id)` |
| rename / synopsis / plotline / page-status | `FieldEdit(id, field, before, after)` |
| link/unlink beat, link/unlink causal | `RefEdit(id, ref, before, after)` (add ⇄ remove) |
| realize | `Realize(cardId, scene…)` — see §5 |
| detach | `Detach(cardId, sceneId)` — undo re-attach, redo detach (no file touched; the scene already exists) |

`content` for a card = everything needed to recreate it identically: title, body, and its front-matter
metadata (plotline, page-status, beat links, causal links, scene ref). Captured **at the instant of
deletion**, before the file is gone (ADR-0050 §1 — "a deleted node speaks at the instant of death").

### 4. The one required backend capability: create-a-card-with-a-supplied-id (restore)

`CreateCard.redo` and `DeleteCard.undo` must land the **same** id, or beat/causal refs pointing at the card
(and the card's own refs) would dangle. Cards make this natural: a card's canonical identity is its
front-matter `id`, not its filename (ADR-0048). So the cards create endpoint gains an optional
caller-supplied id + full content, and rejects a **collision** (the id is already live) so undo/redo can
never duplicate. This is the ADR-0050 §6 identity invariant, made concrete for a file-backed node. No other
new backend surface is required for the card ops.

### 5. Realize-undo deletes the minted scene — but only when the card is its sole referent, and behind a suppressible confirm

Realize is the one op that mints a **scene file**, and it is exactly what ADR-0048 §S13 worried about.
Cardinality is **0..n cards per scene** (ADR-0048), so a scene can be shared. Therefore:

- `Realize.undo` **detaches** the card from the scene, and **deletes the scene only if no other live card
  references it**. A shared scene is kept (undo just detaches); a sole-referent scene is deleted.
- A scene deletion is **destructive and irreversible-feeling** (it takes the scene's prose and its
  snapshots — ADR-0043: a scene and its snapshots are one deletion unit). So it is **guarded by a confirm**
  that **names the scene and its snapshot count** (ADR-0043's deletion-confirmation precedent), with the
  usual **"don't show this again" checkbox** (`dontShowAgainKey`) — Anton's explicit call. When the box is
  ticked, later realize-undos delete silently.
- `Realize.redo` re-mints a **fresh** scene and re-attaches. A fresh scene id is safe precisely because the
  scene was deleted only when it had no surviving referents, so nothing dangles. (A shared scene was never
  deleted, so redo of *that* undo just re-attaches the existing scene — the command records which path it
  took.)

This keeps "undo means undo" while refusing to silently shred a shared scene or a scene the writer has since
filled with prose.

### 6. Multi-command ops group as one step (ADR-0050 §4)

Seed (N cards) and realize (delete-scene + detach, or mint + attach) emit several commands under a shared
transaction id, so **one Ctrl+Z reverses the whole gesture**. The common single-op path stays
one-command-one-step. No new transaction machinery — ADR-0050 §4's implicit shared-id run already does this.

### 7. Fold in the keyboard-reach fix so Ctrl+Z actually reaches the board

Independently of scope, board Ctrl+Z is broken today: the chord handler on the `.plot-board` `<section>`
rides bubbling from a focused descendant, but plot cards are `selectable:false`, so a mouse interaction
never lands DOM focus inside the board (the view designer works only because its nodes are selectable). Fix:
`tabindex="-1"` on the section + focus it on board pointerdown / dragstop. Small, self-contained, lands here
so "Ctrl+Z undoes everything" is true by key as well as by button. (The Undo *button* already works — it
calls `undo()` directly.)

## Why / rejected alternatives

- **Whole-state / scene-file snapshots (ADR-0048 §S13's floated option).** Rejected for the same reasons
  ADR-0050 rejected them, plus a new one here: a snapshot-restore would clobber concurrent edits and fight
  the file-based source-of-truth, and it is *coarser* than the problem — most content ops are a single
  field flip that a `{before, after}` command reverses exactly. The id-carrying command dissolves the only
  advantage snapshots had (no id bookkeeping). **This is the settled position; it is not to be reopened.**
- **Inverse-command without a stored id (recreate = mint a new id).** Rejected — a redo-of-create or
  undo-of-delete that minted a fresh id would dangle every beat/causal ref pointing at the card. ADR-0050 §6
  is not optional here.
- **Realize-undo always deletes the scene.** Rejected — with 0..n cards per scene, that orphans other
  cards' attachments. §5 deletes only a sole-referent scene.
- **Realize-undo never deletes the scene (just detach, leave the file).** Rejected — it leaks an orphan
  scene the writer never chose to keep, and it makes undo a lie (the mint is not reversed). §5 deletes when
  safe, behind a confirm.
- **A synchronous caretaker that fires the inverse call and does not await.** Rejected — mashed Ctrl+Z would
  overlap inverse calls and race the refetch. §2's await + busy-gate is the minimal fix.
- **Persistent, cross-reload undo.** Out of scope (ADR-0050 §5): in-session only, uniform with the rest of
  the app.

## Consequences

- The board's content-op store helpers stop being fire-and-forget: each also `record`s its inverse command.
  A mechanical, local change per call site (mutate-via-endpoint as before, plus record).
- The shared `GraphUndoController` gains **async command support** (await `undo()`/`redo()`, expose a
  `busy` state the controls gate on). Still domain-agnostic. This is a real but small addition to ADR-0050's
  slice-0 caretaker; the view designer's sync commands are unaffected (awaiting a resolved value is a no-op).
- The cards create endpoint gains an **optional supplied id + collision rejection** (restore). One new
  backend affordance; no new endpoint family.
- Content undo is a **server round-trip** (the inverse call), unlike layout undo. Acceptable — a content
  edit is a server mutation both ways.
- Realize gains a **suppressible destructive confirm** on undo (ADR-0042 pattern, `dontShowAgainKey`).
- The board's Ctrl+Z starts working (§7). The "Undo layout" label becomes "Undo".
- ADR-0048 §S13's deferred undo item is **closed**; the branch's "undo revisited against snapshots" future
  is answered against snapshots.

## Non-goals

- **Undoing prose edits *inside* a scene.** TipTap owns that (ProseMirror history); realize/detach/delete of
  the scene are board ops, the words within it are not.
- **Cross-pane / app-wide undo.** Board-scoped, per ADR-0050 §3.
- **Persistent undo across reload.** In-session only (ADR-0050 §5).
- **Reworking layout undo.** Drags already work; this only adds content ops beside them.

## Open — to settle at implementation

- **Rail ops in v1?** create/delete plotline and create/delete arc (the rails, #737/#863) are content ops
  too. Leaning: include them (same `Create/Delete(id, content)` shape, same restore need for plotline/arc
  ids) — but they may slice after the card ops if the restore surface differs. Named, not fixed.
- **Field-edit coalescing.** Rapid synopsis keystrokes → one command per commit, or coalesced? ADR-0050's
  open item; default per-commit (each save is one command), the same answer the view designer takes.
- **Busy-gate UX.** Whether the in-flight state shows a spinner on the control or just disables it (0005's
  lesson — commit to *a* gate, not its pixels).
- **Seed transaction size.** A large seed is N create commands in one transaction; confirm the caretaker's
  bounded-stack depth (ADR-0050 open item) treats the transaction, not each command, as the unit.

## User journeys (definition of done)

- **Seed, oops.** Writer seeds from the manuscript → 40 cards appear → Ctrl+Z → all 40 vanish in **one**
  step → Ctrl+Y → all 40 return. (Transaction, §6.)
- **Delete, restore.** Writer deletes a card that fulfils beat X and leads-to card Y → Ctrl+Z → the card is
  back **with its beat link and its causal edge intact** (same id, §4).
- **Realize, reconsider (sole scene).** Writer realizes a card → a fresh scene is minted → writes nothing →
  Ctrl+Z → a confirm: *"Undo realize — this deletes the scene 'Chapter 3 draft' and its 2 snapshots."*
  [✓ don't show again] → confirmed → scene gone, card unattached.
- **Realize a shared beat.** Two cards already point at scene S; the writer realizes a third card onto S →
  Ctrl+Z → the card just **detaches**; S is untouched (its other two cards keep it), no confirm.
- **Reassign, revert.** Writer moves a card from plotline A to B → Ctrl+Z → back on A. (FieldEdit.)
- **Keyboard.** After any of the above, Ctrl+Z reaches the board without first clicking a control (§7).

## Test surface

- **Command round-trips (pure, where the command logic can be isolated from the canvas):** create → undo
  deletes → redo recreates with the same id; delete → undo recreates (id + refs) → redo deletes; field
  edit → undo restores `before`; seed transaction collapses to one undo step.
- **Identity invariant (backend):** create-with-supplied-id lands that id; a collision is rejected; a
  deleted-then-undone card carries its original id and its beat/causal refs resolve.
- **Realize-undo cardinality (backend):** undo of a realize onto a **sole-referent** scene deletes the scene
  (+ its snapshots); undo of a realize onto a **shared** scene only detaches and leaves the scene live.
- **Async gate (in-app, not headless):** a command in flight disables undo/redo; a mashed Ctrl+Z does not
  overlap two inverse calls; an inverse-call failure leaves the cursor unadvanced and surfaces the error.
- **Keyboard reach (in-app):** after a mouse drag or click, Ctrl+Z reaches the board caretaker (§7).
- **Confirm (§5):** the realize-undo confirm names the scene + snapshot count and honours
  `dontShowAgainKey`.
