// Pins the #1920 fix: opening the board pane is a fetch-then-show that never
// routes through App's run()/banner — refreshPlotBoard records its own failure
// into plotBoardError and never rejects, so no wrapper is needed here. Moved
// alongside its store (review of #1922, R3) — see plotBoard.ts's header on why.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { openPlotBoardPane } from "./plotBoard";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { api } from "@/lib/api";
import type { PlotBoardProjection } from "@/lib/types";

describe("openPlotBoardPane (#1920)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("refreshes the board projection and brings the pane into view", () => {
    const getProjection = vi
      .spyOn(api, "getPlotBoardProjection")
      .mockResolvedValue({} as PlotBoardProjection);
    const ensureVisible = vi.spyOn(workspaceLayout, "ensureVisible").mockImplementation(() => {});

    openPlotBoardPane();

    expect(getProjection).toHaveBeenCalledOnce();
    expect(ensureVisible).toHaveBeenCalledWith("plotEditor");
  });
});
