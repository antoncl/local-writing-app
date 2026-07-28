<script lang="ts">
  // The proposed-vs-current review for a lore brainstorm commit (ADR-0046
  // slice 2). A `revise:entry` chat finalises and hands its full revised body
  // here; the author reviews it against the entry's current body as the same
  // flip the snapshot compare uses, and adopts region by region.
  //
  // Deliberately the snapshot-adopt shape, not a second write path: adopting a
  // region writes the reprojected body into the live TipTap buffer through
  // `adoptBody` — which marks the pane dirty and autosaves — so the entry is
  // persisted through the door that already exists (ADR-0046 §1; the write is a
  // PUT via the normal lore autosave, not a bespoke endpoint). The orientation
  // (proposal = cool `was`, current = warm `now`) comes from `reviewBodyProposal`
  // and must not be re-diffed the other way (memo #590 / loreRevision.ts).

  import { untrack } from "svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { reviewBodyProposal } from "@/lib/utils/loreRevision";
  import { adoptRegion, renderDiffRuns, type DiffRegion } from "@/lib/utils/diffRuns";
  import type { DiffRun } from "@/lib/types";

  let {
    currentBody,
    proposedBody,
    onAdoptBody,
    onClose,
  }: {
    /** The entry's body as the author currently sees it (the live buffer). */
    currentBody: string;
    /** The full revised body the brainstorm committed. */
    proposedBody: string;
    /** Write the resolved body into the live buffer once, on Done
     *  (proseBodyView.adoptBody, which autosaves). */
    onAdoptBody: (body: string) => void;
    /** Dismiss the review (clear the pending proposal). */
    onClose: () => void;
  } = $props();

  // Snapshot the starting body once, to skip a no-op write on Done. `untrack`
  // states the capture-once intent — this component is remounted per proposal
  // via {#key}, so a new proposal is a fresh mount, never an update.
  const originalBody = untrack(() => currentBody);

  // The run titles reworded for a proposal — "Restore this" is snapshot wording
  // (memo #590). A cool run is the proposal; a warm run is the current wording.
  function loreTitle(kind: DiffRun["kind"], region: DiffRegion): string {
    if (kind === "was") return region.nowText ? "Use this wording" : "Add this";
    return region.wasText ? "Keep this" : "Remove this";
  }

  let runs = $state<DiffRun[]>(untrack(() => reviewBodyProposal(currentBody, proposedBody).runs));
  let changesRemain = $derived(runs.some((run) => run.kind !== "equal"));

  let html = $state("");
  $effect(() => {
    const snapshot = runs;
    let cancelled = false;
    void renderDiffRuns(snapshot, "both", loreTitle).then((rendered) => {
      if (!cancelled) html = rendered;
    });
    return () => {
      cancelled = true;
    };
  });

  // The resolved body accumulates as regions are adopted, but nothing is written
  // to the buffer until Done: a K-region adopt is ONE save (adoptBody autosaves
  // per call), and Discard is a true no-op — the buffer is never touched during
  // review. `adoptRegion` returns the running resolution (the clicked region
  // resolved, the rest still current) as its non-null `body`.
  let pendingBody: string | null = null;

  function handleRunClick(regionId: number, kind: "now" | "was"): void {
    const result = adoptRegion(runs, regionId, kind);
    if (result.body != null) pendingBody = result.body;
    runs = result.runs;
  }

  function done(): void {
    if (pendingBody != null && pendingBody !== originalBody) onAdoptBody(pendingBody);
    onClose();
  }

  function discard(): void {
    // Nothing was written during review, so discarding is just dismissal.
    onClose();
  }
</script>

<div class="lore-revision-review">
  <div class="review-bar">
    <span class="review-hint">
      Proposed revision — click the <span class="was-swatch">dotted</span> wording to adopt it.
    </span>
    <div class="review-actions">
      <button type="button" class="review-discard" onclick={discard}>Discard</button>
      <button type="button" class="review-done" onclick={done}>
        {changesRemain ? "Done" : "Close"}
      </button>
    </div>
  </div>
  <ReadOnlyBodyOverlay
    {html}
    label="Proposed revision (review)"
    tone="snapshot"
    onRunClick={handleRunClick}
  />
</div>

<style>
  .lore-revision-review {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
  }
  .review-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 6px 24px;
    border-bottom: 1px solid color-mix(in srgb, var(--diff-was) 30%, transparent);
    background: color-mix(in srgb, var(--diff-was) 8%, transparent);
  }
  .review-hint {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .was-swatch {
    color: var(--diff-was);
    font-weight: 600;
  }
  .review-actions {
    display: flex;
    gap: 8px;
  }
  .review-actions button {
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 12px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  .review-actions button:hover {
    background: var(--inset);
  }
  .review-done {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
  }
</style>
