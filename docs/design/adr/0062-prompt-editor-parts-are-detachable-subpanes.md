# ADR-0062: A prompt editor part is a detachable, subordinate sub-pane

- Status: **Accepted** — 2026-08-17 (Anton). Approved over the prompt/field-system design session.
- Issue: #1105 · Pre-1.0 (no release milestone)
- Follows: ADR-0030 (the tiled shell — nothing floats/overlaps/cascades; splitters replace move-buttons; the surface taxonomy region/tab/rail/popover/dialog), ADR-0051 (a node owns its conversations — the `parentPaneId` **subordinate-pane** relationship reused here)
- Consumes: ADR-0061 (a snippet carries its fields — the Inputs surface renders the *effective* set, two-tier with provenance)
- Relates: ADR-0038 §A (edit-in-place, compact-at-rest), ADR-0054 (the disposition/commit surface, which stays where it is — see anti-goals)
- **Verified against `f0c20603` (2026-08-16).**

> **Amendment 1 (2026-08-19, S2 implementation).** §4 asserted the draft *must*
> lift into a per-document store, calling it "the real work." Implementation
> found this unnecessary: `SchemaPanes` already runs a subordinate pane off a
> `panelRegistry` **snippet that closes over its live component state**, and
> Svelte 5 propagates reactivity across the `RegionBody` render boundary. So the
> Preview is defined once as a snippet in `CodeBodyView`, rendered inline in the
> split when docked and registered under `preview:<editorPaneId>` when detached —
> **no store, docked path untouched**, its bound-out signals (`diagnostics`,
> `effectiveInputs`) still feeding the docked gutter + Setup tab. This collapsed
> the planned S2a (store lift) + S2b (detach) into **one slice**. The store's
> only edges over the snippet — standalone unit-testing and a path toward the
> deferred OS-window detach — did not justify the extra machinery for this
> per-pane case. §4 and the "keep the draft in `CodeBodyView`" rejected-alternative
> are superseded accordingly.

## Context

A prompt editor exists for one tight loop: **edit the template, watch it render.** But the prompt editor (`CodeBodyView`, inside the shared `NodeEditor` shell) stacks all of a prompt's parts into **one narrow vertical scroll column** — the CodeMirror template, then the `EntryInputsEditor`, then the `OfferOnPicker`, then the `PromptPreviewPane`, each a collapsed `<details>`. The preview loses a four-way fight for that column: in practice it renders **one or two lines**, which makes the loop it exists to serve unusable.

Two axes of the same squeeze: the parts compete for **vertical** space in one column, and the editor pane is often a **narrow** workspace column to begin with. Relabeling or reordering the disclosures doesn't fix either — the parts need *room*, and the loop needs the template and the preview visible *together*.

The app already solved this shape one level up. The **tiled shell** (ADR-0030, #32: `workspaceLayout` / `WorkspaceNode`) gives documents draggable tabs, drop-to-split, and a strict *tiles-never-floats* law. And it already has **subordinate panes**: a chat launched from a node registers against its host pane (`parentPaneId` / `hostPaneId`, ADR-0051) and auto-closes when that pane closes. The pieces to give the prompt editor room already exist; they just haven't been composed at the sub-document level.

## Decision

A prompt editor's parts are **sub-tabs**, and any sub-tab can **detach into its own workspace pane, subordinate to the editor.**

### 1. Sub-tabs: Template · Preview · Setup

The editor body carries three sub-tabs:

- **Template** — the CodeMirror Jinja editor.
- **Preview** — the live rendered output (`PromptPreviewPane`) with its input-value drafts.
- **Setup** — the authoring configuration: **Inputs** (`EntryInputsEditor`) + **Offered-on** (`OfferOnPicker`), folded together so the tab strip stays quiet. Setup is touched occasionally; Template and Preview are the continuous loop.

### 2. A sub-tab detaches into a subordinate workspace pane

Any sub-tab can be **pulled out into its own pane** in the tiled workspace. That pane is **subordinate to the editor**: it closes when the editor closes, it is a *view of the same document* rather than a peer document. A **docked sub-tab and a detached pane are two homes for the same content** — exactly how the shell already lets a document tab move between tab-groups. **Detaching Preview beside the Template is the side-by-side loop** — template and preview both visible, each with its own height *and* width.

### 3. Reuse the shell — one tiling model, subordinate via `parentPaneId`

Detach is **not a new mechanism.** It reuses the shell's tab-DnD + drop-to-split (which *tiles*, never floats) and the `parentPaneId` subordinate-close semantics chats already use. There is **one** tiling model in the app, not a bespoke mini-tiler inside the editor that has to imitate it.

### 4. The one new piece — lift the live draft to a per-document store

Today `CodeBodyView` owns the unsaved draft (body + input drafts + `offer_on`) internally, so preview reads it in-component. For a **detached** preview to render as-you-type, that draft must lift out of the component into a **per-document draft store** that the code pane and any detached pane both subscribe to. This is the real work; sub-tabs, detach, and subordination are composition of existing mechanisms.

### 5. Inputs is a two-tier surface (consumes ADR-0061)

Under ADR-0061 a prompt's inputs are its **effective** set. The Setup tab's Inputs list is therefore **two-tier**: this prompt's own inputs, then inherited-from-snippet inputs grouped by source, the inherited ones read-only with provenance. Giving Inputs a real tab (not a cramped disclosure) is partly *why* — the two-tier list needs the room.

## Why / rejected alternatives

**Sub-tabs alone (one part visible at a time).** Rejected — it *breaks* the core loop. Template and Preview as mutually-exclusive tabs means edit-blind → tab to preview → decode → tab back. The value is seeing them together, which is what detach restores. Tabs are the *compact* arrangement; they are not sufficient on their own.

**A permanent fixed internal split (code | preview), no detach.** Rejected as the *end state* (kept as slice 1). A fixed split fixes the vertical squeeze but not the narrow-pane one — in a slim workspace column both halves are cramped. Detach lets Preview escape the editor's column into open workspace room. (Slice 1 ships the internal split because it makes preview usable *immediately*; detach is the roomy arrangement layered on.)

**A bespoke tab/split system inside the editor.** Rejected — a *second* tiling model that must feel pixel-identical to the shell's or it reads as inconsistent, and drifts from it over time. Reusing `workspaceLayout` keeps one interaction model everywhere.

**Detach to a floating window / overlay.** Rejected — the shell law is *tiles, never floats* (ADR-0030). A detached sub-pane tiles like everything else.

**Keep the draft in `CodeBodyView`; have the preview pane re-read the saved file.** Rejected — preview must reflect the *unsaved* draft as-you-type, and the autosave debounce means the file is stale between keystrokes. The draft has to be shared live (§4).

**Make detached panes peer documents (own tab, own persistence).** Rejected — they are *views of one document*, not documents. Peerhood would put a prompt's preview in Recents, let it outlive its editor, and require reconciling two "open" identities for one node. Subordinate-and-ephemeral is the honest model.

## Anti-goals

- **Nothing floats.** Detached panes tile (ADR-0030). No overlap, no cascade, no free geometry.
- **Not everything detaches.** Preview earns it; Setup rarely needs it. This is not "four co-equal panes" — over-fragmenting a narrow editor is the opposite of the fix.
- **Subordinate, not peer.** Detached panes are views of the prompt document: no Recents entry, no independent persistence, they die with the editor.
- **One tiling model.** Reuse the shell; do not grow a parallel mini-tiler.
- **Not a redesign of the disposition/commit surface.** *Where AI output lands* (`output.kind` + `commit`) stays authored in Detail Types (ADR-0054); making it *legible from the prompt editor* is a related UX gap (a read-only disposition line) but a separate change, not folded in here.
- **No pre-1.0 migration** — a spatial reorganisation of the editor; storage is untouched.

## User journey

A writer opens a revise prompt. The body shows three sub-tabs — **Template · Preview · Setup** — Template active. They grab the **Preview** tab and drop it into a split beside the code; now the template is on the left and its rendered messages on the right, each full height. They edit the Jinja and watch the preview re-render live, fill an input value in the preview panel, keep tuning. They flip to **Setup** to add an input and pick where the prompt is offered, flip back. When they close the prompt's editor tab, the detached preview pane closes with it — it was never a document of its own.

## Consequences

- **A sub-tab strip** (Template / Preview / Setup) replaces the stacked-`<details>` composition in `CodeBodyView`.
- **The live draft lifts** out of `CodeBodyView` into a per-document draft store; the code pane and any detached pane bind to it. This is the load-bearing refactor.
- **Detach composes existing machinery** — `workspaceLayout` for the tab/split, `parentPaneId` for subordinate-close — rather than adding a tiling system.
- **Setup folds Inputs + Offered-on**; **Inputs becomes two-tier** once ADR-0061 lands.
- **The preview stops being 1–2 lines** — the acute symptom — from slice 1, before any detach machinery.

## Slice plan — one lane, disjoint, vertical (reorderable)

- **S1 — split + Setup tab (immediately usable preview).** Split the body into **code | preview** with a splitter (the shell's existing splitter pattern), and move Inputs + Offered-on into a **Setup** tab off the main column. Kills the 1–2-line preview with no detach machinery. *(This is the fastest path to the acute fix.)*
- **S2 — the draft-state lift + detach.** Lift the live draft into a per-document store; let a sub-tab detach into a subordinate workspace pane (`parentPaneId`), closing with the editor. Restores the full-room side-by-side loop.
- **S3 — two-tier Inputs.** Own vs inherited-from-snippet inputs with provenance, inherited read-only. **Depends on ADR-0061.**

## Deliberately out of scope (deferred, with a named trigger)

- **Detaching a sub-pane to a separate OS window.** The shell's own detach-to-OS-window is deferred pending packaging (ADR-0030); a sub-pane inherits that deferral. **Trigger:** the shell gains OS-window detach — sub-panes ride it for free.
- **Generalising detachable sub-panes to other editors** (scene, lore, view). Prompt-first, because its edit↔preview loop is the sharpest case. **Trigger:** a second editor whose parts genuinely need the same spatial split — then the mechanism generalises, not speculatively.
- **A read-only disposition line in the prompt editor** (surfacing `output.kind`/`commit` from ADR-0054 where the prompt is authored). Real UX gap, but an additive legibility change independent of the spatial model. **Trigger:** its own slice, once the spatial overhaul settles.
