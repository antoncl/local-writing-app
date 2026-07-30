/**
 * Reviewing a proposed revision of a node's prose body as a flip-diff
 * (ADR-0046 slice 1, #590; generalized to any schema-typed node in ADR-0048 S3).
 *
 * This is the ADR's central claim made concrete on the shape we already ship:
 * a proposed body is reviewed against the entry's current body through the
 * **same** `DiffRun` flip the snapshot compare uses — no new renderer, no new
 * write path. The two sides are a *parameter*, not snapshot-specific (ADR-0046
 * §Consequences), so this module supplies them for the proposed-vs-current case
 * and hands the rest straight to the existing `diffRuns` / `groupRuns` /
 * `adoptRegion` machinery in `diffRuns.ts` (#419) and `snapshotDiff.ts` (#573).
 *
 * **Which side is which — and why the proposal is cool.** `diffRuns(was, now)`
 * is called with the proposal as `was` and the current body as `now`, so the
 * live entry is the warm `now` side and the AI's proposal is the cool `was`
 * side. That tint is a deliberate decision (#590), not an accident of reuse:
 * warm reads as "what is in the entry now", cool as "a candidate that is not in
 * the entry yet" — the same reading as snapshot compare (warm = the live scene,
 * cool = the stored alternative). It also keeps a reused invariant intact — the
 * run reassembly and `adoptRegion` treat `now` as the live baseline, so
 * declining every region is a no-op on the live body. Only the run *titles*
 * baked into `renderDiffRuns` ("Restore this") are snapshot wording the UI slice
 * will reword for a proposal; the *tint* is correct as-is and needs no override.
 *
 * **One diff owns the runs.** `diffRuns` is not guaranteed boundary-symmetric
 * across orientation — its block alignment has direction-dependent tie-breaks —
 * so a consumer must render and adopt the runs THIS module returns and never
 * re-diff current-vs-proposal the other way round to recolour: the region ids
 * would not be guaranteed to line up, and adopt would corrupt against them.
 */
import { groupRuns } from "@/lib/utils/diffRuns";
import { diffRuns } from "@/lib/utils/snapshotDiff";
import type { DiffRegion } from "@/lib/utils/diffRuns";
import type { DiffRun } from "@/lib/types";

/** The reviewable diff of a proposed body against the current one. `runs` feed
 *  the existing flip renderer (`renderDiffRuns`) exactly as a snapshot compare
 *  does; `regions` are the adopt units — one per contiguous change, the ids the
 *  author accepts or declines. Empty `regions` means the proposal is identical
 *  to the current body. */
export type BodyRevision = {
  runs: DiffRun[];
  regions: DiffRegion[];
};

/** One text-bearing field a brainstorm patch proposes, reviewed as its own
 *  run-diff flip (ADR-0046 §6.3 slice 3a): the field's current value vs the
 *  proposed one, plus the label the flip renders under. */
export type FieldFlip = {
  fieldId: string;
  label: string;
  currentValue: string;
  proposedValue: string;
};

/**
 * Diff a proposed body against the current one into the flip's `DiffRun` shape.
 *
 * `diffRuns(was, now)` with the proposal as `was` and the current body as `now`
 * (see the module note): the runs then reassemble to the current body on the
 * `now` side and the proposed body on the `was` side, the same invariant every
 * consumer of these runs relies on.
 */
export function reviewBodyProposal(currentBody: string, proposedBody: string): BodyRevision {
  const runs = diffRuns(proposedBody, currentBody);
  return { runs, regions: groupRuns(runs).regions };
}
