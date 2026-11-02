// @vitest-environment happy-dom
// The card-height estimate reads the text scale the card's CSS uses: the root's
// `--ui-scale` (#2362). The pure maths is pinned in plotBoardLayout.test.ts.
import { afterEach, describe, expect, it } from "vitest";
import { CONTAINER_HEADER, DECK_SYNOPSIS_LINE_H, boardTextScale, estCardHeight, estPlotNodeHeight } from "./boardGeometry";
import { boardBoxes } from "./boxLayout";
import type { PlotBoardProjection } from "@/lib/types";

describe("boardTextScale (#2362)", () => {
  afterEach(() => {
    document.documentElement.style.removeProperty("--ui-scale");
  });

  it("reads the root's --ui-scale, which the default estimate then uses", () => {
    document.documentElement.style.setProperty("--ui-scale", "1.5");
    expect(boardTextScale()).toBe(1.5);
    expect(estCardHeight("t", "s", 2)).toBe(estCardHeight("t", "s", 2, 1.5));
    expect(estCardHeight("t", "s", 2)).toBeGreaterThan(estCardHeight("t", "s", 2, 1));
  });

  it("scales the plotline/arc node estimate, so the arc band clears a scaled plotline", () => {
    expect(estPlotNodeHeight(7, 1.3)).toBeGreaterThan(estPlotNodeHeight(7, 1));
    document.documentElement.style.setProperty("--ui-scale", "1.3");
    expect(estPlotNodeHeight(7)).toBe(estPlotNodeHeight(7, 1.3));
  });

  it("scales a box's header, and a deck's synopsis lines under it", () => {
    const projection: PlotBoardProjection = {
      board_id: "b",
      board_revision: "r",
      layout: {},
      plotlines: [],
      arcs: [],
      containers: [{ id: "ch", title: "ch", parent: null }],
      decks: [{ id: "d", title: "d", synopsis: "one\ntwo", parent: null, movable: true }],
      cards: [],
      diagnostics: [],
    } as PlotBoardProjection;
    document.documentElement.style.setProperty("--ui-scale", "1.5");
    const header = (nodeId: string) => boardBoxes(projection).find((b) => b.nodeId === nodeId)!.header;
    expect(header("container:ch")).toBe(Math.ceil(CONTAINER_HEADER * 1.5));
    expect(header("deck:d")).toBe(Math.ceil((CONTAINER_HEADER + 2 * DECK_SYNOPSIS_LINE_H) * 1.5));
  });

  it("is 1 when the root carries no scale, or a value that isn't a positive number", () => {
    expect(boardTextScale()).toBe(1);
    document.documentElement.style.setProperty("--ui-scale", "nonsense");
    expect(boardTextScale()).toBe(1);
  });
});
