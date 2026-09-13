// Pins the #1920 fix: opening the board pane is a fetch-then-show that never
// routes through App's run()/banner — refreshPlotBoard records its own failure
// into plotBoardError and never rejects, so no wrapper is needed here.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { openPlotBoardPane } from "./paneOpeners";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";

vi.mock("@/lib/stores/plotBoard", () => ({ refreshPlotBoard: vi.fn().mockResolvedValue(undefined) }));

describe("openPlotBoardPane (#1920)", () => {
  beforeEach(() => {
    vi.mocked(refreshPlotBoard).mockClear();
  });

  it("refreshes the board projection and brings the pane into view", () => {
    const ensureVisible = vi.spyOn(workspaceLayout, "ensureVisible").mockImplementation(() => {});

    openPlotBoardPane();

    expect(refreshPlotBoard).toHaveBeenCalledOnce();
    expect(ensureVisible).toHaveBeenCalledWith("plotEditor");
  });
});
