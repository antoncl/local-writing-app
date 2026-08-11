// Plot-board drag-and-drop payloads (#824). Linking a beat to a card is a drag from
// the Arcs rail (the palette) onto the card — the origin/plotting prototype's gesture,
// ported to the current SvelteFlow board. The payload rides HTML5 `dataTransfer` under
// a custom MIME so the board can tell a beat-drag from any other drag, with a
// `text/plain` fallback for good measure.
//
// Why a custom MIME and not just text/plain: during `dragover` the browser withholds
// the DATA (only `types` is readable, for security), so the drop target checks
// `hasPlotBeatDrag` (a `types` membership test) to decide whether to accept — and reads
// the real payload only on `drop`, when `getData` is allowed. A discriminated `kind`
// keeps room for future drag kinds (e.g. moving a badge card→card) in one channel.

export const PLOT_DND_MIME = "application/x-local-writing-plot";

// A beat dragged from the Arcs rail: which beat of which arc (template instance).
export type PlotBeatDrag = { kind: "beat"; instance: string; beat_id: string };

export function setPlotBeatDrag(event: DragEvent, instance: string, beat_id: string): void {
  const dt = event.dataTransfer;
  if (!dt) return;
  const payload: PlotBeatDrag = { kind: "beat", instance, beat_id };
  dt.setData(PLOT_DND_MIME, JSON.stringify(payload));
  dt.setData("text/plain", `${instance}:${beat_id}`);
  dt.effectAllowed = "copy"; // a beat drop CREATES a link (copy), never moves the source
}

// True when the current drag carries a plot-beat payload. Safe to call during
// `dragover` (reads `types`, not the withheld data), so the card can highlight + accept.
export function hasPlotBeatDrag(event: DragEvent): boolean {
  return !!event.dataTransfer && event.dataTransfer.types.includes(PLOT_DND_MIME);
}

// Read the beat payload on `drop`. Returns null for a non-beat drag or malformed data,
// so the drop handler no-ops rather than throwing on someone else's drag.
export function readPlotBeatDrag(event: DragEvent): PlotBeatDrag | null {
  const raw = event.dataTransfer?.getData(PLOT_DND_MIME);
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as unknown;
    if (
      payload &&
      typeof payload === "object" &&
      (payload as PlotBeatDrag).kind === "beat" &&
      typeof (payload as PlotBeatDrag).instance === "string" &&
      typeof (payload as PlotBeatDrag).beat_id === "string" &&
      (payload as PlotBeatDrag).instance &&
      (payload as PlotBeatDrag).beat_id
    ) {
      return payload as PlotBeatDrag;
    }
  } catch {
    // Malformed JSON in the drag channel — not one of ours; ignore.
  }
  return null;
}
