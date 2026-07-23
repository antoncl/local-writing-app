// What a notch says about time (#458; ADR-0044 §D, §L).
//
// **The strip reads `content_written_at`, never `captured_at`.** An automatic
// capture fires before the save, so its bytes are the previous sitting's while
// its record is made at the start of this one — the two can be a fortnight
// apart. Explicit captures were dated correctly, so laying out by record time
// meant automatic and explicit notches on one age-laid-out track described
// different things with nothing to tell them apart.
//
// It lives here, out of the component, because that rule needs an oracle: the
// four sites that read a snapshot's time are all in `.svelte` files, there is no
// component test harness, and the first version of this fix could be reverted
// field-by-field with the whole suite green. A helper the components can only
// spell one way is what makes the rule testable.
//
// Ordering belongs here for the same reason it belongs *together with* the
// ages: position and list order have to come off the same key, or ← / → walk one
// sequence while the eye reads another.
import type { Snapshot } from "@/lib/types";
import { relativeTime } from "@/lib/utils/relativeTime";
import { ageMinutes } from "@/lib/utils/snapshotTrack";

/** Milliseconds for an ISO stamp; `0` (the epoch, so: oldest) if unparsable. */
function stamp(at: string): number {
  const value = new Date(at).getTime();
  return Number.isFinite(value) ? value : 0;
}

/**
 * The listing in the order the strip draws it — **oldest content first**, which
 * is `notchPositions`' input contract.
 *
 * The backend lists by `captured_at`, because record time is monotonic and is
 * what thinning means by "the oldest". Content time is not monotonic and is not
 * even always in step with it: an mtime can move backwards relative to record
 * order after a restore from backup, a cloud sync, an NTP correction, or across
 * the upgrade window, where a legacy record falls back to its `captured_at`
 * while a newer one carries genuinely older content. Whenever it does,
 * `notchPositions`' left-to-right gap pass would draw the older body to the
 * *right* of the newer one — tooltipped "an hour ago" at the fresh end — and
 * ← / →, which walk list order, would step visually backwards.
 *
 * Record time breaks ties, so repeated captures of unchanged content (which
 * share an mtime by construction) keep the order they were taken in.
 */
export function inNotchOrder(snapshots: readonly Snapshot[]): Snapshot[] {
  return [...snapshots].sort(
    (a, b) =>
      stamp(a.content_written_at) - stamp(b.content_written_at) ||
      stamp(a.captured_at) - stamp(b.captured_at),
  );
}

/** Each snapshot's age in minutes, by **content** time, against one clock — so
 *  every notch and tick on a paint shares it. */
export function notchAges(snapshots: readonly Snapshot[], now: Date = new Date()): number[] {
  return snapshots.map((snapshot) => ageMinutes(snapshot.content_written_at, now));
}

/** How a snapshot's time is phrased wherever the strip says it out loud: the
 *  notch tooltip, the actions row, the editor's ribbon. */
export function notchWhen(snapshot: Snapshot | null | undefined, now: Date = new Date()): string {
  return relativeTime(snapshot?.content_written_at ?? "", now);
}

/**
 * A notch's tooltip. Most snapshots have no description — every automatic one,
 * and every explicit one taken in flow — so slice 1's tooltip is the date line
 * alone (§L: the absent case is the COMMON case and must read well on its own).
 * A description is an enrichment on top of it, and arrives with slice 4.
 */
export function notchTooltip(snapshot: Snapshot, now: Date = new Date()): string {
  const when = notchWhen(snapshot, now);
  return snapshot.retention === "kept" ? `Snapshot · ${when} · kept` : `Snapshot · ${when}`;
}
