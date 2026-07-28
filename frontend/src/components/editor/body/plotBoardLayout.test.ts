import { describe, expect, it } from "vitest";

import type { PlotBoardCard, PlotBoardLayout, StructureDocument } from "@/lib/types";
import { buildColumns, buildFlowNodes, buildLayoutNodes, groupNodeId } from "./plotBoardLayout";

const structure: StructureDocument = {
  root: {
    id: "root",
    type: "scene:root",
    title: "Book",
    children: [
      {
        id: "act_one",
        type: "scene:act",
        title: "Act I",
        children: [
          {
            id: "chapter_one",
            type: "scene:chapter",
            title: "Opening",
            children: [],
          },
        ],
      },
      {
        id: "act_two",
        type: "scene:act",
        title: "Act II",
        children: [],
      },
    ],
  },
};

describe("buildFlowNodes", () => {
  it("wraps root containers into a second row when the horizontal run is too wide", () => {
    const manyActs: StructureDocument = {
      root: {
        id: "root",
        type: "scene:root",
        title: "Book",
        children: ["one", "two", "three", "four"].map((id) => ({
          id: `act_${id}`,
          type: "scene:act",
          title: `Act ${id}`,
          children: [],
        })),
      },
    };

    const nodes = buildFlowNodes([], buildColumns(manyActs, []), null, []);
    const thirdAct = nodes.find((node) => node.id === groupNodeId("act_three"));

    expect(thirdAct?.position.y).toBeGreaterThan(0);
  });

  it("restores persisted act positions and dimensions", () => {
    const cards: PlotBoardCard[] = [
      {
        id: "card_opening",
        title: "Opening",
        synopsis: "",
        node_ref: null,
        structure_column_id: "chapter_one",
        primary_plotline_id: null,
        metadata: {},
      },
    ];
    const layout: PlotBoardLayout = {
      nodes: [
        {
          id: groupNodeId("act_two"),
          kind: "group",
          position: { x: 80, y: 360 },
          cfg: { width: 520, height: 420 },
        },
      ],
      edges: [],
      viewport: null,
    };

    const nodes = buildFlowNodes(cards, buildColumns(structure, cards), layout, []);
    const act = nodes.find((node) => node.id === groupNodeId("act_two"));

    expect(act?.position).toEqual({ x: 80, y: 360 });
    expect(act?.width).toBe(520);
    expect(act?.height).toBe(420);
    expect(act?.data.kind).toBe("group");
    if (act?.data.kind === "group") {
      expect(act.data.minWidth).toBeGreaterThan(0);
      expect(act.data.minHeight).toBeGreaterThan(0);
    }
  });

  it("serializes cards and root act dimensions into persisted layout nodes", () => {
    const nodes = buildFlowNodes([], buildColumns(structure, []), null, []);
    const layoutNodes = buildLayoutNodes(nodes);
    const act = layoutNodes.find((node) => node.id === groupNodeId("act_one"));

    expect(layoutNodes.some((node) => node.id === groupNodeId("chapter_one"))).toBe(false);
    expect(act?.cfg.width).toBeGreaterThan(0);
    expect(act?.cfg.height).toBeGreaterThan(0);
  });
});
