<script lang="ts">
  // One proposed-vs-current prose flip (ADR-0046 §2). Extracted from the
  // slice-2 review so a lore commit can review the body AND each text-bearing
  // long_text field as the SAME run-diff flip — the body seam applied to a
  // named field value (§6.3). The orientation (proposal = cool `was`, current =
  // warm `now`) comes from `reviewBodyProposal` and must not be re-diffed the
  // other way (memo #590 / entryRevision.ts).
  //
  // Self-contained: captures its starting text once (it is {#key}-remounted per
  // proposal), accumulates the resolution as regions are adopted, and reports
  // the running resolved value up via `onResolved` — null while unchanged from
  // the original, so the parent can save only what actually moved, once, on Done.

  import { untrack } from "svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { reviewBodyProposal } from "@/lib/utils/entryRevision";
  import { adoptRegion, renderDiffRuns, type DiffRegion } from "@/lib/utils/diffRuns";
  import type { DiffRun, DiffView } from "@/lib/types";

  let {
    currentText,
    proposedText,
    label,
    view = "both",
    onResolved,
  }: {
    /** The value as the author currently sees it (the warm `now` side). */
    currentText: string;
    /** The value the brainstorm committed (the cool `was` side). */
    proposedText: string;
    /** Section heading — "Body", or a long_text field's label. */
    label: string;
    /** Which whole version to read (#710): `both` interleaves the diff, `now`
     *  shows the current text whole, `was` the proposed text whole. The runs
     *  carry both versions, so a change is a re-render, never a re-diff. */
    view?: DiffView;
    /** Report the running resolution: null while unchanged from the original. */
    onResolved: (value: string | null) => void;
  } = $props();

  const originalText = untrack(() => currentText);

  // Run titles reworded for a proposal — "Restore this" is snapshot wording
  // (memo #590). A cool run is the proposal; a warm run is the current wording.
  function flipTitle(kind: DiffRun["kind"], region: DiffRegion): string {
    if (kind === "was") return region.nowText ? "Use this wording" : "Add this";
    return region.wasText ? "Keep this" : "Remove this";
  }

  let runs = $state<DiffRun[]>(untrack(() => reviewBodyProposal(currentText, proposedText).runs));

  let html = $state("");
  $effect(() => {
    const snapshot = runs;
    const activeView = view;
    let cancelled = false;
    void renderDiffRuns(snapshot, activeView, flipTitle).then((rendered) => {
      if (!cancelled) html = rendered;
    });
    return () => {
      cancelled = true;
    };
  });

  function handleRunClick(regionId: number, kind: "now" | "was"): void {
    const result = adoptRegion(runs, regionId, kind);
    if (result.body != null) {
      onResolved(result.body === originalText ? null : result.body);
    }
    runs = result.runs;
  }
</script>

<div class="revision-flip">
  <div class="flip-label">{label}</div>
  <ReadOnlyBodyOverlay {html} {label} tone="snapshot" onRunClick={handleRunClick} />
</div>

<style>
  .revision-flip {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .flip-label {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
    padding: 8px 24px 2px;
  }
</style>
