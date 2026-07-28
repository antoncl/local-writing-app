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
 * **Which side is `now`.** `adoptRegion` and the run reassembly ride one
 * invariant: the *live* document is the `now` side, so the baseline (adopt
 * nothing) is `now`. A lore entry's live body is `currentBody`, so `currentBody`
 * is `now` and the proposal is `was` — forced, not a preference. Accepting a
 * proposed region therefore takes its `was` text; declining keeps `now`. (The
 * warm/cool tint and the run `title`s were written for snapshot-vs-live and read
 * oddly against a proposal — "Restore this" on the AI's text. That is a review
 * *surface* question the ADR defers to the UI slice; this module commits only to
 * the body arithmetic, which the tint does not affect.)
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
