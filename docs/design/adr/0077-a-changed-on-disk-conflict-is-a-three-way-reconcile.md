# ADR-0077: A changed-on-disk conflict is a three-way reconcile, not a question

- Status: **Proposed** — 2026-08-29. Checked against a cold-implementer pass over the save/reconcile
  path (the three legs a merge needs, and which one the pane doesn't hold).
- Verified against `458f9917` (2026-08-29).
- Feature: #72 · Builds on the 2-way reconcile (`minimalReplaceTransaction`, #694 / PR #1320) · Follows
  ADR-0050 (undo is a per-surface caretaker; the in-editor prose history this preserves is the library
  history ADR-0050 keeps distinct), ADR-0043/0044 (the flip diff renderer the dialog reuses) · Relates
  ADR-0039 (every editable kind shares the `base_revision` guard).
- Supersedes nothing. Turns the 2-way reconcile (#694) into its three-way generalization; the 2-way case
  folds in as the local-empty degenerate.

## Problem

The changed-on-disk 409 only ever **asks**. `handleSaveFailure` (`editorPaneSave.ts:125`) routes a 409 to
`offerCloseConflictRecovery` / `offerAutosaveConflictRecovery` (`:145` / `:170`), which raise a "Changed
on disk" modal offering **Overwrite / Discard / Keep** (`:148`, `:173`). That is an escape hatch, not a
resolution: it fires on every 409, including the ones the app could settle itself.

Three facts frame the fix:

- **The backend signal is coarse.** `save_scene` raises `ProjectServiceError(…, 409)` on
  `request.base_revision and request.base_revision != current_revision` (`manuscript.py:521`) — a
  revision-token inequality, with no diff and no base payload. The same guard sits on the other editable
  kinds (lore, plot, prompt, project node, views, mutation sets, assistants, research), so this is
  cross-kind, not scene-specific.
- **The app already reconciles a changed doc into a live editor without losing undo.**
  `minimalReplaceTransaction` (`documentBoundary.ts:47`) diffs the incoming doc against the live one with
  ProseMirror's own `findDiffStart` / `findDiffEnd` (`:53`, `:55`) and replaces **only** the changed
  range as an `addToHistory:false` transaction (`:66`), so prosemirror-history maps the author's undo
  trail *through* it (#694). But it is **2-way** — live vs remote, remote wins in the changed range — and
  its own consumer comment names the missing piece: *"closing that needs a baseline + step rebase"*
  (`ProseBodyView.svelte`, the flush→reconcile window). That baseline-plus-rebase is this ADR.
- **The pane holds two of the three legs a merge needs.** `baselineBody = pane.scene.body`
  (`editorPanes.svelte.ts:542`) is the last-loaded on-disk body — the natural **base**; `pane.draftMarkdown`
  is the **local** edits. The **remote** leg — what is on disk *now* — is not retained anywhere.

## Decision

**A changed-on-disk conflict is auto-reconciled by a three-way merge on the ProseMirror document; the
author is asked only when local and remote edited the same region.**

### 1 — Three legs; the remote leg is fetched on conflict, not held

`base` = the last-loaded body (`pane.scene.body`); `local` = the live editor doc (`pane.draftMarkdown`);
`remote` = re-fetched on the 409 (`api.getScene`, and its per-kind siblings). Fetch-on-conflict rather
than hold-always: a conflict is rare, and on-disk content drifts after load, so a third copy carried in
the pane would be both wasteful and stale.

### 2 — The primitive: a three-way reconcile on the ProseMirror doc

Generalize the `minimalReplaceTransaction` recipe from *"replace the one changed range"* to *"rebase
`local`'s change-set over `remote`'s via ProseMirror position `Mapping`"*, applied as an
`addToHistory:false` transaction so the undo trail survives exactly as it does for the 2-way reconcile.
The existing 2-way reconcile is the **degenerate case** (empty `local`) and folds into it. The exact
step-derivation and mapping composition are slice B's to build — the decision here is the **technique and
the contract**, not the algorithm.

### 3 — The ladder (#72's three rungs)

1. **Rung 1 — lost response.** On a 409, if the fetched `remote` equals the pane's **last-sent** content,
   the save actually landed (backend restart, dropped response) and only the pane went stale: adopt the
   new revision **silently**. Content equality, no merge, applies to every kind.
2. **Rung 2 — disjoint.** Run the three-way reconcile; if `local` and `remote` changed **non-overlapping**
   regions, apply the merged doc through the existing reconcile path and re-save at the fresh revision.
   Silent.
3. **Rung 3 — overlap.** The "Changed on disk" dialog survives as the escape hatch, upgraded from a blind
   Overwrite/Discard to a **diff preview** (reusing the ADR-0044 flip renderer, as ADR-0046 already does
   for patch review).

### 4 — What "conflict" means, and the conservative bias

- **Prose:** a conflict is when `local` and `remote` changed the **same span** (their diff ranges
  overlap). Disjoint spans merge.
- **Structured content** (metadata, `mutation_set` rows, override deltas): a conflict is the **same field**
  changed to different values. Disjoint fields merge.
- **Prove-disjoint-or-ask.** When disjointness cannot be established, fall to the dialog. A confident-but-
  wrong silent merge corrupts a document, which is strictly worse than one more question; the bias is
  always toward asking, never toward guessing.

### 5 — One ladder, a merge mechanism per content shape

The `base_revision` 409 is shared across kinds (ADR-0039), so the ladder runs for **every** editable kind.
What it dispatches to follows the content shape: prose bodies use the ProseMirror three-way reconcile
(§2); structured fields use a **field-level** disjoint merge under the same disjoint/overlap contract
(§4). Two mechanisms, one ladder.

## Why / rejected alternatives

- **Keep the dialog (status quo).** The escape hatch *is* the complaint (#72): it asks on every 409,
  including the lost-response and disjoint cases the app can resolve. Kept only as rung 3.
- **Remote-wins 2-way reconcile (what #694 does today).** In any region `remote` also touched it silently
  discards the author's unsaved `local` edits — data loss. Rejected as the resolution; retained as the
  local-empty degenerate case of the three-way primitive.
- **Line-based text diff3 over the Markdown.** Merges the *serialized* form — losing document structure
  and the undo trail (the very reasons the app reconciles through `minimalReplaceTransaction` rather than
  `setContent`), and re-solving what ProseMirror's position mapping already does. Rejected.
- **Hold the remote leg always** (so a 409 needs no fetch). A third copy carried for a rare event, and
  stale the moment disk changes after load. Fetch-on-conflict is cheaper and correct. Rejected.
- **Full live collaboration now** (`prosemirror-collab` / Yjs). A different model — a central OT/CRDT
  authority with a websocket channel, per-document sessions, and an update-stream store — for an app whose
  source of truth is the file on disk. Out of scope for 1.0, and its mechanism is deliberately **not**
  sketched here. The one forward commitment is that revision-as-content-hash stays compatible with a
  future converge-then-write.

## Consequences

- The two resolvable cases (lost-response, disjoint edits) stop asking; the dialog narrows to genuine
  same-spot conflicts and gains a diff preview.
- The undo trail survives the merge — the `addToHistory:false` reconcile transaction is the in-editor
  prose-history sibling of ADR-0050's command caretaker (which the prose editor's own library history sits
  beside, per that ADR).
- **A reusable primitive, named but not pre-wired.** A three-way reconcile is content-convergence
  machinery, not conflict-specific, and the shape recurs: adopting an AI-committed patch into an entry the
  author edited meanwhile (ADR-0046/0063), restoring a snapshot into a live editor (ADR-0043/0044). This
  ADR does **not** build those consumers or reserve hooks for them — it records the recurrence so the
  primitive is a general `(base, local, remote) → { doc, conflicts }` function beside `documentBoundary.ts`,
  not logic inlined in the 409 handler. Whether those features adopt it is their design's call.
- One extra round-trip — the `remote` fetch — on a 409, a rare path.
- Conflict detection must be conservative; the failure to avoid is a confident-but-wrong silent merge, so
  the contract is prove-disjoint-or-ask.
- **Backend unchanged.** The coarse `base_revision` 409 stays; the whole ladder is frontend, over content
  the backend already serves. The issue's converge-then-write compatibility holds because `revision` is
  already a content hash.
- Two merge mechanisms live under one ladder (prose reconcile, structured field-merge) — named here so
  slice C is planned, not discovered.

## Acceptance (from #72)

- A lost-response 409 (`remote` == last-sent) adopts the new revision with **no** dialog.
- Disjoint `local`/`remote` edits merge and adopt with **no** dialog, and the undo trail is preserved.
- An overlapping edit shows the dialog with a **diff preview**, not a blind choice.
- The ladder runs across document kinds (the shared `base_revision` path), dispatching to the merge
  mechanism the content shape needs.

## Slices

1. **Rung 1 — lost-response adopt.** On a 409, fetch `remote`; if it equals the last-sent content, adopt
   silently. All kinds; this builds the fetch-on-409 plumbing rungs 2–3 reuse. The smallest slice and the
   "why am I being asked?" win.
2. **Rung 2 — prose three-way reconcile.** Generalize `minimalReplaceTransaction` to the base/local/remote
   rebase; disjoint → apply + re-save, overlap → fall to the dialog. Scenes first, then the other prose
   bodies.
3. **Rung 2 structured field-merge + Rung 3 diff-preview dialog.** Field-level disjoint merge for metadata
   / rows; upgrade the "Changed on disk" dialog from a blind choice to a diff preview.

Sequential (each builds on the prior). Binding = the Decision + the prove-disjoint-or-ask contract (§4);
the slice boundaries may shift if implementation argues for it, amending this ADR before code.
