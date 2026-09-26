<script lang="ts">
  // A generic single-region adopt flip (ADR-0096 §4/§6, S3): the non-prose
  // half of a list unit — a differing scalar member, an addition, a removal,
  // or the order — rendered through the SAME run machinery the body's own
  // flip uses (`renderDiffRuns`/`adoptRegion`), never a bespoke toggle. The
  // twin of `RevisionFlip`, minus the prose-specific "declined back to the
  // original" bookkeeping: a unit here settles to whichever side survives the
  // click, and the caller (`ListReviewSection`) is the one that knows what
  // "adopted" means for its kind of unit.
  import { untrack } from "svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { adoptRegion, renderDiffRuns } from "@/lib/utils/diffRuns";
  import type { DiffRun, DiffView } from "@/lib/types";

  let {
    runs: initialRuns,
    label,
    view = "both",
    adoptable = true,
    onSettle,
  }: {
    /** The region's runs — one or two stacked runs (ADR-0096 §6). */
    runs: DiffRun[];
    /** An accessible label for the overlay (the member/unit name). */
    label: string;
    view?: DiffView;
    /** False where the list cannot be written (ADR-0096 §6, an override
     *  layer): the comparison shows, but no region is clickable. */
    adoptable?: boolean;
    /** Reports whether the click adopted O's side (`adoptRegion`'s
     *  `body !== null`) — the caller maps that to its unit's resolution. */
    onSettle: (adopted: boolean) => void;
  } = $props();

  // Captured once (like `RevisionFlip`'s own runs) — a unit is remounted
  // per comparison, never fed a live-updating `runs` prop.
  let runs = $state<DiffRun[]>(untrack(() => initialRuns));
  let html = $state("");

  $effect(() => {
    const snapshot = runs;
    const activeView = view;
    let cancelled = false;
    void renderDiffRuns(snapshot, activeView).then((rendered) => {
      if (!cancelled) html = rendered;
    });
    return () => {
      cancelled = true;
    };
  });

  function handleRunClick(regionId: number, kind: "now" | "was"): void {
    const result = adoptRegion(runs, regionId, kind);
    onSettle(result.body !== null);
    runs = result.runs;
  }
</script>

<ReadOnlyBodyOverlay {html} {label} tone="snapshot" onRunClick={adoptable ? handleRunClick : undefined} />
