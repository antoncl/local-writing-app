// Plot-board drag-and-drop payloads (#824; ADR-0053). Linking a beat to a card is a
// drag of a beat from its plotline onto the card — the origin/plotting prototype's
// gesture, ported to the current SvelteFlow board (S4 sources the drag from the
// plotline node). The payload rides HTML5 `dataTransfer` under a custom MIME so the
// board can tell a beat-drag from any other drag, with a `text/plain` fallback.
//
// Why a custom MIME and not just text/plain: during `dragover` the browser withholds
// the DATA (only `types` is readable, for security), so the drop target checks
// `hasPlotBeatDrag` (a `types` membership test) to decide whether to accept — and reads
// the real payload only on `drop`, when `getData` is allowed. A discriminated `kind`
// keeps room for future drag kinds (e.g. moving a badge card→card) in one channel.

export const PLOT_DND_MIME = "application/x-local-writing-plot";

// A dragged beat: which beat of which plotline. `from` is the SOURCE card id when the
// drag started on a card's badge (#941) — dropping on another card MOVES the link off
// `from`; it is absent when the drag started on the plotline node (a fresh LINK, #824).
export type PlotBeatDrag = { kind: "beat"; plotline: string; beat_id: string; from?: string };

export function setPlotBeatDrag(event: DragEvent, plotline: string, beat_id: string, from?: string): void {
  const dt = event.dataTransfer;
  if (!dt) return;
  const payload: PlotBeatDrag = from ? { kind: "beat", plotline, beat_id, from } : { kind: "beat", plotline, beat_id };
  dt.setData(PLOT_DND_MIME, JSON.stringify(payload));
  dt.setData("text/plain", `${plotline}:${beat_id}`);
  // A badge drag MOVES the link off its source card; a plotline-node drag COPIES (links).
  dt.effectAllowed = from ? "move" : "copy";
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
      typeof (payload as PlotBeatDrag).plotline === "string" &&
      typeof (payload as PlotBeatDrag).beat_id === "string" &&
      (payload as PlotBeatDrag).plotline &&
      (payload as PlotBeatDrag).beat_id
    ) {
      const p = payload as PlotBeatDrag;
      // `from` is optional; keep it only when it's a non-empty string (a card-badge drag).
      return typeof p.from === "string" && p.from ? p : { kind: "beat", plotline: p.plotline, beat_id: p.beat_id };
    }
  } catch {
    // Malformed JSON in the drag channel — not one of ours; ignore.
  }
  return null;
}
