// Pure-logic test for the plot-board layout (ADR-0048 S7b). The SvelteFlow canvas
// itself is not headless-testable ([[reference_svelteflow_headless_limits]]), so
// the board's real logic — lane bucketing, positions, and the derived card/lane
// data — is verified here (node env, no DOM); the custom nodes carry their own
// mount tests, and the composition is browser-checked.
import { describe, expect, it } from "vitest";
import {
  buildBoardNodes,
  CARD_GAP_X,
  CARD_HEIGHT,
  CARD_WIDTH,
  LABEL_TO_CARD_GAP,
  LANE_LABEL_WIDTH,
  ROW_STRIDE,
  UNASSIGNED_LANE_ID,
  type PlotCardData,
  type PlotLaneData,
} from "./plotBoardLayout";
import type { PlotBoardProjection } from "@/lib/types";

function projection(over: Partial<PlotBoardProjection> = {}): PlotBoardProjection {
  return {
    board_id: "board_1",
    board_revision: "r1",
    layout: {},
    plotlines: [],
    cards: [],
    ...over,
  };
}

const line = (id: string, title: string, color: string | null = null) => ({ id, title, color });
const card = (
  id: string,
  over: Partial<PlotBoardProjection["cards"][number]> = {},
): PlotBoardProjection["cards"][number] => ({
  id,
  title: id,
  synopsis: "",
  plotline: null,
  scene: null,
  ...over,
});

// Narrow a node's data by type discriminator for the assertions below.
const laneNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotLane");
const cardNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotCard");

describe("buildBoardNodes", () => {
  it("returns no nodes for an empty board", () => {
    expect(buildBoardNodes(projection())).toEqual([]);
  });

  it("makes one lane node per plotline, in projection order and row-strided", () => {
    const nodes = buildBoardNodes(projection({ plotlines: [line("plot_a", "A"), line("plot_b", "B")] }));
    const lanes = laneNodes(nodes);
    expect(lanes.map((l) => (l.data as PlotLaneData).title)).toEqual(["A", "B"]);
    expect(lanes.map((l) => l.position.y)).toEqual([0, ROW_STRIDE]);
    // A plotline with no cards still shows its lane (the thread is always visible).
    expect((lanes[0].data as PlotLaneData).count).toBe(0);
  });

  it("places a plotline's cards in its lane row, flowing rightward", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("plot_a", "A")],
        cards: [card("c1", { plotline: "plot_a" }), card("c2", { plotline: "plot_a" })],
      }),
    );
    const cards = cardNodes(nodes);
    expect(cards.map((c) => c.id)).toEqual(["c1", "c2"]);
    // Both on the lane's row (y=0), stepping by CARD_WIDTH + CARD_GAP_X after the label.
    expect(cards.map((c) => c.position.y)).toEqual([0, 0]);
    expect(cards[0].position.x).toBe(LANE_LABEL_WIDTH + LABEL_TO_CARD_GAP);
    expect(cards[1].position.x).toBe(LANE_LABEL_WIDTH + LABEL_TO_CARD_GAP + (CARD_WIDTH + CARD_GAP_X));
    expect((laneNodes(nodes)[0].data as PlotLaneData).count).toBe(2);
  });

  it("collects unattached-to-plotline cards into a trailing Unassigned lane", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: null })] }),
    );
    const lanes = laneNodes(nodes);
    expect(lanes.map((l) => l.id)).toEqual(["lane:plot_a", UNASSIGNED_LANE_ID]);
    expect((lanes[1].data as PlotLaneData).title).toBe("Unassigned");
    // The card sits in the Unassigned row (the second lane), not lane A.
    expect(cardNodes(nodes)[0].position.y).toBe(ROW_STRIDE);
  });

  it("treats a card pointing at an unknown plotline as Unassigned (defensive)", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_gone" })] }),
    );
    expect(laneNodes(nodes).map((l) => l.id)).toContain(UNASSIGNED_LANE_ID);
    expect((laneNodes(nodes).find((l) => l.id === UNASSIGNED_LANE_ID)!.data as PlotLaneData).count).toBe(1);
  });

  it("omits the Unassigned lane when every card is assigned", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_a" })] }),
    );
    expect(laneNodes(nodes).map((l) => l.id)).toEqual(["lane:plot_a"]);
  });

  it("derives card data: synopsis, scene-attachment, and the plotline colour", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("plot_a", "A", "forest")],
        cards: [
          card("attached", { plotline: "plot_a", synopsis: "she leaves", scene: "scene_1" }),
          card("loose", { plotline: "plot_a", scene: null }),
        ],
      }),
    );
    const [attached, loose] = cardNodes(nodes).map((c) => c.data as PlotCardData);
    expect(attached).toMatchObject({ synopsis: "she leaves", attached: true, color: "forest" });
    expect(loose).toMatchObject({ attached: false, color: "forest" });
  });

  it("gives Unassigned cards a null colour", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { plotline: null })] }));
    expect((cardNodes(nodes)[0].data as PlotCardData).color).toBeNull();
  });

  it("sizes nodes from the geometry constants (single source with the CSS)", () => {
    // Node size is set here, not measured by SvelteFlow, so position math and the
    // rendered box can't drift — the components fill their box at 100%.
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_a" })] }),
    );
    expect(laneNodes(nodes)[0]).toMatchObject({ width: LANE_LABEL_WIDTH, height: CARD_HEIGHT });
    expect(cardNodes(nodes)[0]).toMatchObject({ width: CARD_WIDTH, height: CARD_HEIGHT });
  });
});
