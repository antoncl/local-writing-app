// The AI-review freeze wiring (#634 / ADR-0046), factored out of NodeEditor so the
// reactivity contract is unit-testable in isolation (the autosave.ts precedent —
// timing/lifecycle concerns live in editor-core siblings, not the mega-component).
//
// A node under an open brainstorm review is a frozen transaction: the host tells
// the pane controller to suppress autosave (committer non-null) while `reviewing`,
// and to thaw (null) the instant the review ends or the pane unmounts.
//
// #1965 — the trap this closes. `App.svelte` passes the freeze `signal`
// (onReviewFreeze) as an INLINE arrow, which it recreates on every render. Reading
// that callback *tracked* inside the effect made the effect re-run on every
// unrelated App render. Each re-run's cleanup thawed (`endReviewLock`) and its body
// re-froze (`beginReviewLock`) — and `beginReviewLock`, seeing `firstLock` true
// again on a DIRTY pane, re-fired its flush-on-enter `saveEditorPane`. When that
// save kept 409ing (a sibling surface — e.g. the plot board — moved the plotline on
// disk, so the pane's `base_revision` was stale), the failing save mutated `panes`,
// which re-rendered App, which recreated the arrow, which re-ran the effect: an
// unbounded ~81/s PUT loop (~127k requests in one report) that only a component
// teardown cleared.
//
// The fix: the effect must fire only on a genuine review-state transition — the
// entry id or `reviewing` changing — never on the host callback's identity churn.
// So `signal` (and the committer it is handed) are read through `untrack`; only
// `entryId()` and `reviewing()` are tracked dependencies.
//
// The Accept-all 409 loop — the same engine, a second fuel line. `entryId()` is
// `scene?.id`, and reading it tracks the SCENE OBJECT, which the pane store
// replaces on every `panes` reassignment (a failed save's `saving` flip among
// them). An unchanged id still re-ran the effect, so a dirty review pane whose
// save kept 409ing looped exactly as above (~8k PUTs in two minutes). Both inputs
// now pass through `$derived`, which notifies only when the VALUE changes.
import { untrack } from "svelte";
import type { ReviewCommitter } from "@/lib/stores/editorPanes.svelte";

/** Freeze/thaw a node's review: called with the committer while the review is up,
 *  and with `null` the moment it ends (or the host unmounts). */
export type ReviewFreezeSignal = (entryId: string, committer: ReviewCommitter | null) => void;

/** Wire the freeze effect from four host getters. Must be called during the host
 *  component's initialization (it registers a `$effect`). Fires `signal` exactly on
 *  the review-state transitions of `entryId()` / `reviewing()`; the host may pass a
 *  `signal` (and `committer`) whose identity churns every render without re-firing it
 *  (#1965). */
export function wireReviewFreeze(deps: {
  entryId: () => string | null;
  reviewing: () => boolean;
  committer: () => ReviewCommitter;
  signal: () => ReviewFreezeSignal | undefined;
}): void {
  const trackedEntryId = $derived(deps.entryId());
  const trackedReviewing = $derived(deps.reviewing());
  $effect(() => {
    const entryId = trackedEntryId;
    if (!entryId) return;
    // Tracked: the true transition signal. The rest is read out-of-band below.
    const active = trackedReviewing;
    untrack(() => deps.signal()?.(entryId, active ? deps.committer() : null));
    return () => deps.signal()?.(entryId, null);
  });
}
