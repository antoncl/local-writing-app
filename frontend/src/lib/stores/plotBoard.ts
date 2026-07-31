// Plot-board domain store (ADR-0048 S7b) — the projection the PlotEditor board
// renders from. Unlike the always-loaded slices (structure/lore/…), the board is
// heavy (a SvelteFlow canvas) and needed only while its pane is open, so it is
// refreshed by the opener on demand (mirrors chats/assistants), NOT on project
// open. `null` = not loaded yet; the pane shows nothing until a refresh resolves.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { PlotBoardProjection } from "@/lib/types";

export const plotBoardStore = writable<PlotBoardProjection | null>(null);

export async function refreshPlotBoard(): Promise<void> {
  plotBoardStore.set(await api.getPlotBoardProjection());
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
}
