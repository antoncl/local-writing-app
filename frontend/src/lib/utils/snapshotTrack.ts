// Where the notches sit on the snapshot strip (ADR-0044 §D).
//
// Pure, and separate from the component, because the geometry is the part with
// invariants worth pinning: monotonic in age, never touching, never leaving the
// track. The component only paints what this returns.
//
// **Spacing is the timeline.** Notches sit at their age, so the gaps carry
// meaning: a tight cluster is an afternoon's work, a long run is a week away
// from the scene. That is also why it cannot be linear — one snapshot from last
// week plus four from this morning piles the recent four into an unreadable
// clump at the right edge, and those are the ones an author reaches for. A log
// scale spreads recent history and compresses deep history.
//
// Known ambiguities, stated so they are not later mistaken for defects:
//
// - under keep-five thinning a gap can mean "a week passed" or "a snapshot used
//   to be there". A lone explicit notch far left is "the oldest thing I chose to
//   keep", not "the oldest thing that existed".
// - captures of *unchanged* content share a content time (#458), so `MIN_GAP`
//   draws them a gap apart although no time passed between them. That gap
//   encodes nothing; it is the price of notches that never touch and stay
//   individually clickable, and the identical date lines are the tell.
//
// Positions are percentages of the track, and the track's width is a function
// of the pane's width and nothing else (§E) — so nothing here reads a pixel
// measurement, and no state other than the timestamps can move a notch.

/** Percent of the track. Right of `TRACK_RIGHT` is reserved for Live. */
export const TRACK_LEFT = 1;
export const TRACK_RIGHT = 88;
export const LIVE_LEFT = 96;

/** Minimum distance between two notches, in percent — they never touch,
 *  however they bunch. */
export const MIN_GAP = 4.5;

/** The floor on the scale's span, in minutes. Without it a scene whose
 *  snapshots are all minutes old divides by ~0 and the notches scatter to the
 *  extremes; an hour is the shortest span worth drawing. */
const MIN_SPAN_MINUTES = 60;

/** Faint labelled ticks make the scale legible rather than merely implied. */
export const TICKS: readonly { minutes: number; label: string }[] = [
  { minutes: 60, label: "1h" },
  { minutes: 1440, label: "1d" },
  { minutes: 10080, label: "1w" },
];

/** Where a given age falls on the log scale, before the minimum-gap pass.
 *  Age 0 (now) sits at `TRACK_RIGHT`; the oldest sits at `TRACK_LEFT`. */
export function agePosition(ageMinutes: number, spanMinutes: number): number {
  const span = Math.log(1 + Math.max(MIN_SPAN_MINUTES, spanMinutes));
  const age = Math.log(1 + Math.max(0, ageMinutes));
  return TRACK_LEFT + (TRACK_RIGHT - TRACK_LEFT) * (1 - age / span);
}

/** The span the scale is drawn against: the oldest snapshot's age, floored. */
export function trackSpanMinutes(agesMinutes: readonly number[]): number {
  return Math.max(MIN_SPAN_MINUTES, ...agesMinutes, 0);
}

/**
 * Notch positions for `agesMinutes` — **oldest first** — as percentages of the
 * track.
 *
 * That precondition is `inNotchOrder`'s job, not the backend listing's: the
 * listing is by record time and this is fed content time, and the two can
 * disagree (#458). The gap pass below only ever pushes rightwards, so an
 * unsorted input draws an older body to the right of a newer one.
 *
 * Two passes after the log placement, and the order matters. The gap pass walks
 * left to right pushing crowded notches apart, which can push the newest past
 * `TRACK_RIGHT`; the squeeze pass then scales the whole run back inside. Doing
 * it the other way round would let the squeeze re-close gaps the first pass had
 * just opened.
 */
export function notchPositions(agesMinutes: readonly number[]): number[] {
  if (agesMinutes.length === 0) return [];
  const span = trackSpanMinutes(agesMinutes);
  const positions = agesMinutes.map((age) => agePosition(age, span));

  for (let i = 1; i < positions.length; i++) {
    if (positions[i] - positions[i - 1] < MIN_GAP) positions[i] = positions[i - 1] + MIN_GAP;
  }

  const last = positions[positions.length - 1];
  if (last > TRACK_RIGHT && last > TRACK_LEFT) {
    const scale = (TRACK_RIGHT - TRACK_LEFT) / (last - TRACK_LEFT);
    for (let i = 0; i < positions.length; i++) {
      positions[i] = TRACK_LEFT + (positions[i] - TRACK_LEFT) * scale;
    }
  }
  return positions;
}

/** Age in minutes of an ISO timestamp. Field-agnostic on purpose — the strip
 *  ages notches by `content_written_at`, never `captured_at` (#458), and naming
 *  the parameter for either field would assert a choice that belongs to the
 *  caller (`notchAges`). Negative ages (clock skew) clamp to 0 — a snapshot
 *  cannot be in the future, and letting one through would put a notch to the
 *  right of Live. */
export function ageMinutes(at: string, now: Date = new Date()): number {
  const stamp = new Date(at).getTime();
  if (!Number.isFinite(stamp)) return 0;
  return Math.max(0, (now.getTime() - stamp) / 60_000);
}
