# ADR-0050: Undo/redo is a dumb caretaker over self-reporting reversible commands

- Status: **Draft** — 2026-07-29. Framed with Anton in conversation: the whole-state-snapshot
  first cut was rejected in favour of the command pattern once a **second** node-based surface
  entered the picture; the caretaker is domain-agnostic; transactions are an implicit shared-id run;
  commands carry reversal closures and history is in-session only. Awaiting his review of this
  written form before Accepted.
- Feature: **#187** (view designer has no undo/redo) is the first consumer and the reason this is
  written now. Implementation issues to be filed per slice on approval (§7).
- Follows: ADR-0038 (view-designer UX — the canvas this first lands on), the NodeEditor body-view
  model (each body view owns its own editing affordances), ADR-0030 (the editing surface should feel
  uniform across body views).
- Relates: **ADR-0048** (plot boards — "a board of card nodes") is the anticipated **second**
  consumer; this ADR exists so undo/redo is a shared mechanism it reuses rather than a thing
  reinvented per node surface. This ADR does **not** design the plot board's command vocabulary.

> **Code references.** This ADR describes **roles and behaviours**, not call sites. Claims about
> *current* behaviour were verified against **`c387f71` (2026-07-29)** and are true of that tree only.
> Symbols are named before locations; a reader arriving later should re-verify before acting, and
> treat a disagreement with the code as evidence the ADR aged, not that the code is wrong.

## Context

The view-designer body (`ViewBodyView`, the SvelteFlow canvas) has **no undo/redo**. Adding, deleting,
wiring, configuring, and moving nodes are all irreversible except by hand (#187). The other NodeEditor
body views do have it, so the designer reads as a gap in an otherwise-uniform editing surface.

How the other two body views get undo today matters, because "reuse the same affordances" (#187) turns
on it. **They each own their library's built-in history, and there is no shared undo bus.** ProseBodyView
builds TipTap with `StarterKit`, which bundles ProseMirror's `history` plugin and its Mod-Z / Mod-Shift-Z
keymap; the component's own keydown handler intercepts Ctrl+J / Tab / arrows and lets Z/Y fall through to
that history. CodeBodyView delegates to `CodeEditor`, whose `basicSetup` includes CodeMirror's `history()`
+ `historyKeymap` (Ctrl+Z / Ctrl+Y). The only window-level keydown handler in `App.svelte`
(`handleWorkspaceKeydown`) claims F6 / Ctrl+M / Ctrl+1–9 and **never touches Z/Y**. So the precedent is
**per-surface history, each owning its own stack**, fired by Ctrl+Z while that surface is focused — not a
central undo manager the surfaces subscribe to.

The view designer's whole state already lives in two Svelte-5 rune arrays in `ViewBodyView`, `flowNodes`
and `flowEdges` (each node carrying `{kind, cfg}`), bound directly to the canvas. Graph mutations
funnel through a handful of committers on the designer context — `updateNodeData`, `removeNode`,
`addNode`, and edge changes via `normalizeEdges` / SvelteFlow's delete key. Node **position** is held in
`Node.position` and persisted as a side-channel `layout` (it is not part of the semantic `spec`); a drag
boundary already exists — a `dragging` flag toggled by `onnodedragstart` / `onnodedragstop`, which the
autosave effect already uses to coalesce a drag into a single save. There is **no** existing undo/history
utility to reuse (the many `snapshot*` files are document version history, ADR-0043/0044 — a different
feature). Saving is **autosave, in-memory-first**: mutations land in the rune arrays and a debounced
effect PUTs the view; nothing round-trips before the state changes.

Two facts set the altitude of this decision:

1. **A second node-based surface is coming** — the plot board (ADR-0048, a board of card nodes) is the
   likely candidate, but the design commits to none: the second surface is a fact, its identity a guess.
   Undo/redo
   is not a view-designer feature; it is a mechanism two surfaces will share. Building it into
   `ViewBodyView`'s `flowNodes`/`flowEdges` would be a one-off that the plot board cannot reuse.
2. **The obvious first cut — snapshot the whole `{nodes, edges}` on every change — is the beginner's
   shortcut.** It is simple and cannot desync, and at graph scale (tens of nodes) the memory cost is
   trivial, so it is not *wrong on the memory axis*. It is wrong on the **architecture** axis: it hard-codes
   undo to one surface's state shape, and it buries "what counts as one change" inside a central diff
   instead of leaving it with the thing that knows — the node.

## Decision

### 1. Undo is the **command pattern**: actors self-report reversible changes; the caretaker is dumb

There is **no central "snapshot the world" step**. Each actor **reports its own reversible change** to a
caretaker as it happens, carrying the memento needed to reverse it:

- The **palette** creating a node reports *"I created node N"* (memento = N's birth state). Undo deletes N;
  redo recreates it from the memento.
- A **node** deleting itself reports *"I deleted myself"* **with its full state**, at the moment of
  deletion, before it is gone. Undo recreates it from that state. This is why "a deleted node cannot speak
  for itself" is a non-problem: it speaks at the instant of death.
- A **node** wiring an edge reports *"I spawned an edge to xyz"*. Undo removes the edge; redo re-adds it.

Topology is therefore **not a special case that needs a separate owner** — creation, deletion, and
edge-spawning are just more commands, each owned by whoever performed it. A **command** is a small object
carrying `undo()` / `redo()` (§5). The **caretaker** is an ordered log of executed commands with a cursor;
it holds them and replays them backward/forward. It never inspects a command's contents.

### 2. The caretaker knows **only commands and transaction ids — never nodes or edges**

The caretaker's entire vocabulary is "a reversible command" and "a transaction id" (§4). It has no concept
of a node, an edge, a position, or a graph. `node` / `edge` / `config` / `topology` are **command types the
view designer defines**, not types the caretaker knows.

This is the load-bearing constraint, and it is what makes the mechanism reusable: the plot board (ADR-0048)
mounts the **same** caretaker and emits **its own** command vocabulary (cards, columns, attachments),
without the shared layer changing or knowing anything about cards. If any graph-specific concept leaked into
the caretaker, the second surface could not reuse it — so nothing graph-specific does. This is why feature
#2's internals are **not needed** to build the shared layer: the contract is "reversible commands," and the
only obligation is that the caretaker stay ignorant of what a command reverses.

### 3. Each node surface owns its **own caretaker instance** — no app-wide undo bus

Consistent with the prose/code precedent (Context): a Ctrl+Z is scoped to the surface that has focus, and
each surface owns its own history. The view designer mounts one caretaker; the plot board mounts another;
TipTap and CodeMirror keep theirs. There is **no shared, app-wide undo bus** that all surfaces feed — that
would be a cross-cutting mechanism the app does not have and does not need, and it would make "undo" mean
different things depending on which pane last mutated. The *code* for the caretaker is shared (§2); the
*instances and their histories* are per-surface.

The designer's Ctrl+Z / Ctrl+Y handler is scoped to the `.view-designer` section (its `onfocusin` already
marks focus entry), **not** `svelte:window`, so it cannot fire while a TipTap or CodeMirror surface in
another pane is focused. Ctrl+Z → undo; **Ctrl+Y and Ctrl+Shift+Z** → redo (TipTap uses the latter, so
matching both is what makes redo feel uniform). SvelteFlow already claims its delete key but not Z/Y, so
there is no conflict on the canvas.

### 4. Transactions are an **implicit shared-id run**, used only by the few cascading ops

Some single gestures emit several commands that must undo as **one** step — deleting a node also removes its
incident edges:

```
node → ⟨transaction N⟩ delete edge a
node → ⟨transaction N⟩ delete edge b
node → ⟨transaction N⟩ delete self
… next command carries no N — transaction N is closed
```

A run of commands sharing a transaction id `N` collapses into **one** undo step. The op that cascades
(delete, and later paste / multi-select drag) opens `N` and tags its commands; **there is no explicit
close** — the transaction ends when the next command arrives without `N`. A command carrying no id is its
own single-step transaction. So the **common path stays trivial — one command, one step** — and only the
handful of cascading ops opt into grouping. No `commit()`, no try/finally, no transaction framework.

Undo reverses an `N` run **LIFO** (recreate self → re-add edge b → re-add edge a); redo replays it forward.
This is correct because the cascade is **synchronous** — the whole `N` run lands before any next user action,
so nothing can interleave into the middle of a transaction.

### 5. A command carries **reversal closures**; history is **in-session only**

A command is `{ undo(), redo() }` (plus an optional transaction id). Closures are the simplest and most
flexible form — the command captures exactly the state it needs to reverse itself, and the caretaker stays
oblivious. The cost is that closures are **not serializable**, so the undo history **does not survive a
reload**.

That is the right trade here: TipTap's and CodeMirror's histories are also in-session only, so an
in-session designer history is **uniform with the rest of the app**, not a regression. The one thing this
forecloses is persistent undo across a reload; if that is ever wanted, commands become **data** (a typed
memento plus a per-type reverser the caretaker dispatches) instead of closures — a larger change, called
out here so the door is visible, not silently shut.

### 6. Invariant: a recreated node returns with its **same id**

When undo recreates a deleted node, it must come back with the **same id** it had, so the edges re-added in
the same transaction reconnect to it instead of dangling. The delete command's memento therefore carries
**identity**, not just shape. This is the one correctness invariant the command authors must honour; the
caretaker cannot enforce it (it never sees an id).

### 7. Slicing — the caretaker first, then the designer's commands, then the second surface reuses it

Each slice states the **user journey that is its definition of done**.

0. **The caretaker + command/transaction protocol.** The domain-agnostic caretaker controller (named to
   avoid the repo's overloaded "history" — chat history, snapshot version history are unrelated): `record`,
   `undo`, `redo`, `canUndo` / `canRedo`, bounded stack, redo cleared on a new command, implicit shared-id
   transactions (§4). A **pure `*.svelte.ts` rune store with a `.test.ts`** — SvelteFlow is not
   headless-testable, so the logic *must* live outside the canvas, and this layer knows no SvelteFlow at
   all. *Done when:* unit tests drive lone commands and a multi-command transaction through
   record/undo/redo and assert one Ctrl+Z reverses a whole transaction.
   - *Not:* anything that imports a node, an edge, or SvelteFlow.
1. **The view designer emits commands.** The committers (`updateNodeData`, `removeNode`, `addNode`,
   `normalizeEdges`, and the drag boundary) each `record` a reversible command instead of only mutating the
   rune arrays; delete opens a transaction over its edge removals + self-removal (§4); a drag records **one**
   command on `onnodedragstop` using the pre-drag positions captured on `onnodedragstart`. A
   designer-scoped keydown wires Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z (§3).
   - *Done when:* in the running app, the author deletes a wired node and Ctrl+Z restores it **with its
     edges**; drags a node and Ctrl+Z reverts the whole drag in **one** step; edits a config field and
     Ctrl+Z reverts that edit; Ctrl+Y / Ctrl+Shift+Z redo each.
   - *Not:* a whole-`{nodes,edges}` snapshot pushed per change (§Why); and not a shared window-level handler
     (§3).
2. **The second surface reuses the caretaker.** When the plot board (ADR-0048) is built, it mounts the same
   slice-0 caretaker and defines its own card/column commands. This slice is **named, not designed here** —
   it is the reason slice 0 is domain-agnostic, and its acceptance is that the board needed **zero** change
   to the caretaker.

The commitment that must hold from slice 0: the caretaker never learns what a command reverses (§2).

## Why / rejected alternatives

- **Snapshot the whole `{nodes, edges}` state on every change (the first cut).** Simple, can't desync, cheap
  at graph scale — but it hard-codes undo to `ViewBodyView`'s specific state shape, so the second node
  surface (ADR-0048) cannot reuse it, and it puts "what counts as one change" in a central diff instead of
  in the node that performs the change. Fine for *one* surface; wrong the moment there are **two**. Rejected
  — the command pattern is the same effort spread to the right owners and it generalizes for free.
- **A caretaker that understands nodes / edges / graph topology.** Would couple the shared layer to the view
  designer's model and overfit it; the plot board could not reuse it without the caretaker growing card
  concepts too. §2 keeps the caretaker ignorant of everything a command reverses. Rejected.
- **A shared, app-wide undo bus across every editing surface.** The prose and code editors each own their
  library history (Context); a bus is a mechanism the app does not have, and it would make Ctrl+Z ambiguous
  across panes. Each surface owns its own caretaker instance (§3). Rejected.
- **An explicit transaction framework (`begin` / `commit`, try/finally).** Heavier than the problem: only a
  couple of ops cascade. The implicit shared-id run (§4) keeps the common path at one-command-one-step and
  lets a cascading op opt in with a tag. Rejected.
- **Serializable, persistent undo history.** Would survive a reload but forces every command into a typed
  data memento with a registered reverser, and nothing else in the app persists undo (TipTap/CodeMirror do
  not). Closures + in-session (§5) is uniform and far smaller. Rejected for now; the migration path to data
  commands is named in §5 if persistence is ever wanted.
- **Extend TipTap's / CodeMirror's history to cover the designer.** Their histories are document-model
  specific (ProseMirror steps, CodeMirror changes); a graph is neither. Rejected — the designer gets its own
  caretaker, not a foreign editor's history.

## Consequences

- A new domain-agnostic caretaker controller plus a command/transaction protocol becomes a shared frontend
  primitive; the view designer is its first caller and the second node surface its second, with no caretaker
  change between them.
- The view designer's committers stop being pure state mutators — each also `record`s a reversible command.
  This is a real change to those call sites, but a mechanical, local one (mutate as before, plus record the
  inverse).
- The undo logic is a pure rune store with a unit test; the canvas only calls into it. This is deliberate:
  SvelteFlow is not headless-testable, so the only way to test undo is to keep it out of the component.
- Autosave is unaffected. Undo/redo mutate the same in-memory rune arrays any edit does, so the existing
  debounced persist effect saves the restored state like any other change — no server round-trip for the
  restore itself, and the view `revision` advances normally (an undo is a real edit, persisted).
- New command types (a new node op, or the plot board's card ops) get undo by `record`-ing their inverse;
  the caretaker needs no change to support them.

## Non-goals

- **Persistent undo across a reload.** In-session only (§5), uniform with the other body views. The path to
  persistence (data commands) is named but not built.
- **A shared app-wide undo bus.** Each node surface owns its own caretaker instance (§3).
- **Changing the prose / code editors' undo.** TipTap and CodeMirror keep their own library history
  untouched.
- **Cross-surface undo.** Undoing in the designer never reaches into a prose or code editor, or another pane.
- **Designing the plot board's command vocabulary.** ADR-0048's surface defines its own commands when it is
  built (§7 slice 2); this ADR only guarantees the caretaker will host them.

## Open — to settle at implementation

- **Per-node change granularity** — whether a node coalesces rapid config edits (e.g. consecutive keystrokes
  in a text config field) into one command, or records one per commit. This is deliberately the **node's**
  call as the command's author (the point of §1), not the caretaker's; settled when the designer's commands
  are written (slice 1). A reasonable default: per-commit, with same-field consecutive-edit coalescing added
  only if it feels janky in use.
- **Whether v1 needs paste / multi-select-drag transactions** — depends on whether the designer has those
  gestures yet; the transaction mechanism (§4) supports them, but the first commands may only need the
  delete cascade.
- **Bounded-stack depth** — a cap on retained commands (memory backstop); a concrete number is an
  implementation detail.

## Test surface

- **Caretaker (slice 0, pure unit tests):** a lone command round-trips through record → undo → redo; a
  three-command transaction (shared id) collapses to **one** undo step and one redo; recording a new command
  after an undo clears the redo stack; the stack is bounded.
- **Identity invariant:** deleting a wired node in one transaction, then undo, returns the node **with its
  original id** and reconnects its edges (not dangling).
- **Drag = one step (in-app, #187 acceptance):** dragging a node then Ctrl+Z reverts the whole drag in a
  single step, not per frame.
- **Focus scoping:** Ctrl+Z while a prose/code surface is focused does not reach the designer caretaker, and
  vice versa.
- **Autosave interplay:** an undo mutates the in-memory arrays and the existing persist effect saves the
  restored state (revision advances); no separate undo endpoint is called.
