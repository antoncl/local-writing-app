// Pins the #1920 fix: the reveal REQUEST opens the board pane itself, rather
// than depending on a shell $effect that raced PlotEditor's own effect and lost.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { get } from "svelte/store";
import { plotBoardReveal, revealOnPlotBoard } from "./plotlines";
import { openPlotBoardPane } from "@/lib/stores/paneOpeners";

vi.mock("@/lib/stores/paneOpeners", () => ({ openPlotBoardPane: vi.fn() }));

describe("revealOnPlotBoard (#1920)", () => {
  beforeEach(() => {
    plotBoardReveal.set(null);
    vi.mocked(openPlotBoardPane).mockClear();
  });

  it("sets the reveal signal and opens the board pane itself", () => {
    revealOnPlotBoard("card_1", "plot:card");

    expect(get(plotBoardReveal)).toEqual({ id: "card_1", entryType: "plot:card" });
    expect(openPlotBoardPane).toHaveBeenCalledOnce();
  });
});
