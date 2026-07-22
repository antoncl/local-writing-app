// Relative real-world time, on a ladder (ADR-0044 §K).
//
// `Intl.RelativeTimeFormat` is built into the browser and produces the
// *5 minutes ago / yesterday* wording for free. **What has to be written is the
// bucketing** — where the ladder switches from relative to named to absolute.
// That is the design decision; a library would make it for us, and wrongly.
//
// Shared rather than inline because it already has a second consumer: the
// snapshot notch tooltip (§L) and ADR-0042's layer-aware footer echo. The
// unrendered `created_at` / `updated_at` on chat sessions are unrendered
// precisely because no formatter existed.
//
// The ladder, and why each rung ends where it does:
//
//   < 1 min      "just now"          — seconds are noise; nobody navigates by them
//   < 1 h        "5 minutes ago"     — the granularity of an actual sitting
//   same day     "3 hours ago"       — still inside the working day you remember
//   yesterday    "yesterday"         — the one named day everybody holds exactly
//   < 7 days     "Wednesday"         — a weekday name is how last week is recalled
//   < 1 year     "Wednesday 12th"    — the year is redundant and adds width
//   older        "12 March 2025"     — past a year, the year is the useful part
//
// The switch from relative to named at one week is the load-bearing choice:
// "6 days ago" is arithmetic the reader has to do, while "Wednesday" is the
// thing they already remember about it.

// **Formatted in English, explicitly — not in the OS locale.** The app has no
// i18n: every other string in the UI is a hardcoded English literal, so letting
// `Intl` follow the system locale produces a mongrel — "for 5 minutter siden"
// sitting next to a button that says Restore, and "onsdag 12th" out of the
// ordinal rung below. This is the app's first rendered date (§K), so the choice
// is being made here rather than inherited; if the app ever grows i18n, this
// constant and the ordinal are the two places that have to move.
const LOCALE = "en-GB";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Midnight local time on the day `at` falls in — day boundaries are what the
 *  ladder's middle rungs are about, and elapsed-hours arithmetic gets them
 *  wrong across an evening. */
function startOfDay(at: Date): number {
  return new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
}

function relative(value: number, unit: Intl.RelativeTimeFormatUnit): string {
  return new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" }).format(value, unit);
}

/** An ordinal day-of-month — "12th". English, like `LOCALE` above and for the
 *  same reason; `Intl` has no ordinal formatter, so this rung is hand-written
 *  either way. */
function ordinal(day: number): string {
  const rest = day % 100;
  if (rest >= 11 && rest <= 13) return `${day}th`;
  return `${day}${["th", "st", "nd", "rd"][day % 10] ?? "th"}`;
}

/**
 * `at` phrased against `now`. Past instants only — a future timestamp is a
 * clock skew or a bad file, and the ladder answers it as "just now" rather
 * than inventing "in 3 minutes" for something that has already happened.
 */
export function relativeTime(at: Date | string | number, now: Date = new Date()): string {
  const when = at instanceof Date ? at : new Date(at);
  const stamp = when.getTime();
  if (!Number.isFinite(stamp)) return "";

  const elapsed = now.getTime() - stamp;
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return relative(-Math.floor(elapsed / MINUTE), "minute");

  const dayDelta = Math.round((startOfDay(now) - startOfDay(when)) / DAY);
  if (dayDelta === 0) return relative(-Math.floor(elapsed / HOUR), "hour");
  if (dayDelta === 1) return relative(-1, "day"); // "yesterday"

  const weekday = when.toLocaleDateString(LOCALE, { weekday: "long" });
  if (dayDelta < 7) return weekday;
  if (now.getFullYear() === when.getFullYear() && dayDelta < 365) {
    return `${weekday} ${ordinal(when.getDate())}`;
  }
  return when.toLocaleDateString(LOCALE, { day: "numeric", month: "long", year: "numeric" });
}
