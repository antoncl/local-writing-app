// Interiority delivery (ADR-0070). A roleplay beat's generation output carries
// two parts: the visible EXTERNAL prose, then — after a line containing exactly
// `[[interiority]]` — the character's private INTERNAL state. The frontend
// splits that stream here; the external becomes the visible beat and the
// internal is stashed on the beat's character mark (hidden, no UI until S2).
//
// The marker is one contract shared across three lockstep sites — keep in sync:
//   - backend/app/builtin_library/prompts/roleplay.md  (instructs the model)
//   - backend/app/services/ai/helpers.py  (INTERIORITY_MARKER — replayed turns)
//   - this file  (splits the stream)
export const INTERIORITY_MARKER = "[[interiority]]";

// The delimiter as it appears in a stream: the marker on its own, tolerant of
// surrounding blank lines and case. Splits external from internal on the first
// occurrence.
const INTERIORITY_SPLIT = /\n*\[\[\s*interiority\s*\]\]\s*\n*/i;

export interface SplitBeat {
  external: string;
  internal: string;
}

/** Split a completed beat into its external prose and private interiority.
 *  No marker → the whole text is external, interiority empty. */
export function splitInteriority(text: string): SplitBeat {
  const idx = text.search(INTERIORITY_SPLIT);
  if (idx === -1) return { external: text, internal: "" };
  const match = INTERIORITY_SPLIT.exec(text);
  const external = text.slice(0, idx);
  const internal = match ? text.slice(idx + match[0].length) : "";
  return { external, internal };
}

/** The external prose to show WHILE streaming: the part before the marker,
 *  with any trailing partial-marker fragment trimmed so a half-arrived
 *  `[[inter…` never flickers into the visible beat. */
export function visibleExternal(accumulated: string): string {
  const { external, internal } = splitInteriority(accumulated);
  // Marker already complete → external is settled.
  if (internal !== "" || accumulated.search(INTERIORITY_SPLIT) !== -1) return external;
  // No complete marker yet — hide a trailing run that is a prefix of the marker
  // (possibly led by newlines), e.g. "…prose\n\n[[inter".
  const partial = /\n*\[\[?\s*i?n?t?e?r?i?o?r?i?t?y?\s*\]?\]?$/i;
  const m = partial.exec(external);
  if (m && m[0].trim() !== "") return external.slice(0, external.length - m[0].length);
  return external;
}
