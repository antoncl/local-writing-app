/**
 * Reviewing a proposed revision of a lore entry's prose body as a flip-diff
 * (ADR-0046 slice 1, #590).
 *
 * This is the ADR's central claim made concrete on the shape we already ship:
 * a proposed body is reviewed against the entry's current body through the
 * **same** `DiffRun` flip the snapshot compare uses — no new renderer, no new
 * write path. The two sides are a *parameter*, not snapshot-specific (ADR-0046
 * §Consequences), so this module supplies them for the proposed-vs-current case
 * and hands the rest straight to the existing `diffRuns` / `groupRuns` /
 * `adoptRegion` machinery in `diffRuns.ts` (#419) and `snapshotDiff.ts` (#573).
 *
 * **No AI here.** In this slice the caller supplies `proposedBody` — a fixture
 * standing in for a model. Slice 2 supplies it from a `revise` prompt; only the
 * *source* of the proposed string changes, and `reviewBodyProposal` /
 * `resolveBody` / `saveAcceptedBody` below are what it inherits.
 *
 * **Which side is which — and why the proposal is cool.** `diffRuns(was, now)`
 * is called with the proposal as `was` and the current body as `now`, so the
 * live entry is the warm `now` side and the AI's proposal is the cool `was`
 * side. That tint is a deliberate decision (#590), not an accident of reuse:
 * warm reads as "what is in the entry now", cool as "a candidate that is not in
 * the entry yet" — the same reading as snapshot compare (warm = the live scene,
 * cool = the stored alternative). It also keeps two reused invariants intact —
 * the run reassembly and `adoptRegion` treat `now` as the live baseline, so
 * declining every region is a no-op on the live body, and `resolveBody`'s
 * "accept = take the proposal" is "take the `was` text". Only the run *titles*
 * baked into `renderDiffRuns` ("Restore this") are snapshot wording the UI slice
 * will reword for a proposal; the *tint* is correct as-is and needs no override.
 *
 * **One diff owns the runs.** `diffRuns` is not guaranteed boundary-symmetric
 * across orientation — its block alignment has direction-dependent tie-breaks —
 * so a consumer must render and adopt the runs THIS module returns and never
 * re-diff current-vs-proposal the other way round to recolour: the region ids
 * would not be guaranteed to line up, and adopt would corrupt against them.
 */
import { api } from "@/lib/api";
import { groupRuns } from "@/lib/utils/diffRuns";
import { diffRuns } from "@/lib/utils/snapshotDiff";
import type { DiffRegion } from "@/lib/utils/diffRuns";
import type { DiffRun, LoreEntry } from "@/lib/types";

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

/**
 * The final body after the author accepts a set of proposed regions.
 *
 * Accept nothing → the current body unchanged. Accept every region → the whole
 * proposed body (the ADR's "accept everything" shortcut, §1). Accept some →
 * those regions take the proposed wording and the rest keep the current — the
 * per-region generalization of `adoptRegion`'s single-region reassembly, over
 * the same `now`/`was` reassembly rule so a mixed result is byte-identical to
 * adopting the regions one at a time.
 */
export function resolveBody(revision: BodyRevision, acceptedRegionIds: Iterable<number>): string {
  const accepted = new Set(acceptedRegionIds);
  const { runs } = revision;
  const { regionIdByRun } = groupRuns(runs);
  let out = "";
  for (let i = 0; i < runs.length; i++) {
    const run = runs[i];
    if (run.kind === "equal") {
      out += run.text;
      continue;
    }
    // Accepted regions take the proposal (`was`); the rest keep the current
    // wording (`now`). A run whose side is not chosen is simply dropped.
    const takeProposed = accepted.has(regionIdByRun[i] as number);
    if (takeProposed ? run.kind === "was" : run.kind === "now") out += run.text;
  }
  return out;
}

/**
 * Adopt the accepted regions and write the result back through the **existing**
 * whole-document lore save (`PUT /api/lore/{id}`) — no new endpoint, no new
 * write path (ADR-0046 §1, and the rejected "per-field mutation endpoint"). The
 * body is assembled client-side by {@link resolveBody} and passed to
 * `api.saveLoreEntry` exactly as a manual edit to the same body would be, so it
 * obeys the ADR-0042 layer routing (`authoringLayerId`) the save already
 * carries.
 */
export function saveAcceptedBody(
  entry: LoreEntry,
  revision: BodyRevision,
  acceptedRegionIds: Iterable<number>,
  authoringLayerId: string | null = null,
): Promise<LoreEntry> {
  const body = resolveBody(revision, acceptedRegionIds);
  // A selection that resolves to the unchanged body is a no-op — declining every
  // region, most obviously. Writing it anyway would mint a pointless revision
  // and can 409 a concurrent editor's optimistic-concurrency check. Mirror
  // `adoptRegion`'s null-body contract ("no write when the body did not change")
  // and skip the save, returning the entry untouched.
  if (body === entry.body) return Promise.resolve(entry);
  return api.saveLoreEntry(entry, body, authoringLayerId);
}
