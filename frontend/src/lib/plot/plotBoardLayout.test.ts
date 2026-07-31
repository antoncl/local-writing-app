// Pure-logic test for the plot-board layout (ADR-0048 S7b). The SvelteFlow canvas
// itself is not headless-testable ([[reference_svelteflow_headless_limits]]), so
// the board's real logic — lane bucketing, positions, and the derived card/lane
// data — is verified here (node env, no DOM); the custom nodes carry their own
// mount tests, and the composition is browser-checked.
import { describe, expect, it } from "vitest";
import {
  buildBoardNodes,
  cardPositionsFromNodes,
  readBoardPositions,
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

  it("makes cards draggable (S7c layout editing) and keeps lane headers fixed", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_a" })] }),
    );
    expect(cardNodes(nodes)[0].draggable).toBe(true);
    expect(laneNodes(nodes)[0].draggable).toBe(false);
  });

  it("applies a saved position override to its card, leaving unsaved cards on the grid", () => {
    const proj = projection({
      plotlines: [line("plot_a", "A")],
      cards: [card("moved", { plotline: "plot_a" }), card("stay", { plotline: "plot_a" })],
    });
    const nodes = buildBoardNodes(proj, { moved: { x: 999, y: 42 } });
    const byId = new Map(cardNodes(nodes).map((c) => [c.id, c]));
    expect(byId.get("moved")!.position).toEqual({ x: 999, y: 42 });
    // The unsaved sibling keeps its derived slot (second column of lane A).
    expect(byId.get("stay")!.position).toEqual({
      x: LANE_LABEL_WIDTH + LABEL_TO_CARD_GAP + (CARD_WIDTH + CARD_GAP_X),
      y: 0,
    });
  });
});

describe("readBoardPositions", () => {
  it("reads well-formed per-card positions out of the opaque layout", () => {
    expect(readBoardPositions({ positions: { c1: { x: 10, y: 20 }, c2: { x: 30, y: 40 } } })).toEqual({
      c1: { x: 10, y: 20 },
      c2: { x: 30, y: 40 },
    });
  });

  it("degrades to no overrides for a missing or malformed layout (the board must render)", () => {
    expect(readBoardPositions({})).toEqual({});
    expect(readBoardPositions({ positions: null } as unknown as Record<string, unknown>)).toEqual({});
    // A partial / non-numeric entry is dropped, valid siblings survive.
    expect(
      readBoardPositions({ positions: { bad: { x: "no" }, ok: { x: 1, y: 2 } } } as unknown as Record<string, unknown>),
    ).toEqual({ ok: { x: 1, y: 2 } });
  });
});

describe("cardPositionsFromNodes", () => {
  it("serializes only card positions, rounded, excluding lane headers", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_a" })] }),
      { c1: { x: 12.4, y: 7.6 } },
    );
    const positions = cardPositionsFromNodes(nodes);
    expect(positions).toEqual({ c1: { x: 12, y: 8 } });
    // No `lane:plot_a` key — lane headers are derived, never stored.
    expect(Object.keys(positions)).toEqual(["c1"]);
  });

  it("round-trips through readBoardPositions", () => {
    const nodes = buildBoardNodes(
      projection({ plotlines: [line("plot_a", "A")], cards: [card("c1", { plotline: "plot_a" })] }),
      { c1: { x: 5, y: 6 } },
    );
    const serialized = { positions: cardPositionsFromNodes(nodes) };
    expect(readBoardPositions(serialized)).toEqual({ c1: { x: 5, y: 6 } });
  });
});
