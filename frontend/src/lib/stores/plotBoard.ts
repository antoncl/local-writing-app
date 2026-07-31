// Plot-board domain store (ADR-0048 S7b) — the projection the PlotEditor board
// renders from. Unlike the always-loaded slices (structure/lore/…), the board is
// heavy (a SvelteFlow canvas) and needed only while its pane is open, so it is
// refreshed on demand (mirrors chats/assistants), NOT on project open. `null` =
// not loaded yet. Two callers refresh it — the menu opener (surfaces errors in
// the banner) and PlotBoardPane on restore (a persisted tab whose store is null
// after reload) — so the fetch is in-flight-guarded to collapse the redundant
// pair into one request.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { PlotBoardLayout, PlotBoardProjection } from "@/lib/types";

export const plotBoardStore = writable<PlotBoardProjection | null>(null);

let inFlight: Promise<void> | null = null;

export function refreshPlotBoard(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = api
    .getPlotBoardProjection()
    .then((projection) => {
      plotBoardStore.set(projection);
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

// Persist the board layout (ADR-0048 S7c) and return the board's advanced
// revision (the mounted editor's next optimistic base). Deliberately does NOT
// touch plotBoardStore: the store's projection is only the editor's initial seed
// (refetched on the next open), and re-setting it would rebuild the canvas from
// under an in-progress edit. The PlotEditor owns the live revision from here on.
export async function savePlotBoardLayout(layout: PlotBoardLayout, baseRevision: string): Promise<string> {
  const saved = await api.savePlotBoard({ base_revision: baseRevision, layout });
  return saved.revision;
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
}
