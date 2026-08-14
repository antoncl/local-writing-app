// Pure-logic test for the plot-board layout (ADR-0048 S7 Slice 4). The SvelteFlow
// canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the board's real logic — container grouping, nesting, positions, and the derived
// card/container data — is verified here (node env, no DOM); the custom nodes carry
// their own mount tests, and the composition is browser-checked.
import { describe, expect, it } from "vitest";
import {
  boardIsEmpty,
  buildBoardNodes,
  containerDescendantIds,
  containerMemberCardIds,
  movableNodePositions,
  containerExtent,
  overriddenNodePositions,
  projectionDataKey,
  readBoardPositions,
  readBoardSizes,
  reconcilePlotlineUiState,
  CARD_GAP_X,
  CARD_HEIGHT,
  CARD_WIDTH,
  CONTAINER_HEADER,
  CONTAINER_PAD,
  type PlotCardData,
  type PlotContainerData,
} from "./plotBoardLayout";
import type { PlotBoardProjection } from "@/lib/types";

function projection(over: Partial<PlotBoardProjection> = {}): PlotBoardProjection {
  return {
    board_id: "board_1",
    board_revision: "r1",
    layout: {},
    plotlines: [],
    containers: [],
    cards: [],
    ...over,
  };
}

const line = (
  id: string,
  title: string,
  color: string | null = null,
  beats: { beat_id: string; title: string; use_count?: number }[] = [],
): PlotBoardProjection["plotlines"][number] => ({
  id,
  title,
  color,
  beats: beats.map((b) => ({ use_count: 0, ...b })),
});
const container = (id: string, title: string, parent: string | null = null) => ({ id, title, parent });
const card = (
  id: string,
  over: Partial<PlotBoardProjection["cards"][number]> = {},
): PlotBoardProjection["cards"][number] => ({
  id,
  title: id,
  synopsis: "",
  plotline: null,
  scene: null,
  container: null,
  page_status: null,
  beats: [],
  sequence: null,
  causal_links: [],
  ...over,
});

const containerNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotContainer");
const plotlineNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotPlotline");
const cardNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotCard");
const dataOf = (nodes: ReturnType<typeof buildBoardNodes>, id: string) => nodes.find((n) => n.id === id)!.data;

describe("buildBoardNodes", () => {
  it("returns no nodes for an empty board", () => {
    expect(buildBoardNodes(projection())).toEqual([]);
  });

  it("nests a card in its chapter box inside its act box", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        cards: [card("c1", { container: "chap", scene: "s1" })],
      }),
    );
    // One box per structural level, act then chapter (act renders behind), then the card.
    expect(nodes.map((n) => n.type)).toEqual(["plotContainer", "plotContainer", "plotCard"]);
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["container:act", "container:chap"]);

    const act = nodes.find((n) => n.id === "container:act")!;
    const chap = nodes.find((n) => n.id === "container:chap")!;
    const c1 = cardNodes(nodes)[0];
    // The card sits at 2·(header+pad) in from the act's top-left (padded through both boxes).
    expect(c1.position).toEqual({ x: 2 * CONTAINER_PAD, y: 2 * (CONTAINER_HEADER + CONTAINER_PAD) });
    // The chapter box wraps the card (pad + header); the act box wraps the chapter box.
    expect(chap.position).toEqual({ x: CONTAINER_PAD, y: CONTAINER_HEADER + CONTAINER_PAD });
    expect(act.position).toEqual({ x: 0, y: 0 });
    expect(act.width).toBe(CARD_WIDTH + 4 * CONTAINER_PAD);
    expect(act.height).toBe(CARD_HEIGHT + 4 * CONTAINER_PAD + 2 * CONTAINER_HEADER);
    // Levels + transitive counts drive the box styling / header.
    expect(dataOf(nodes, "container:act")).toMatchObject({ title: "Act I", count: 1, level: 0 });
    expect(dataOf(nodes, "container:chap")).toMatchObject({ title: "Chapter 1", count: 1, level: 1 });
  });

  it("seeds `measured` on card nodes (not containers) so xyflow can route edges pre-observer", () => {
    // The edge layers (Slice 6a) only draw once both endpoint nodes are measured;
    // xyflow's ResizeObserver may not have run yet (and never does in a headless
    // pane), so buildBoardNodes seeds `measured` from the known geometry. Only
    // cards are edge endpoints, so only cards carry the seed.
    const nodes = buildBoardNodes(
      projection({ containers: [container("act", "Act I")], cards: [card("c1", { container: "act", scene: "s1" })] }),
    );
    expect(cardNodes(nodes)[0].measured).toEqual({ width: CARD_WIDTH, height: CARD_HEIGHT });
    expect(nodes.find((n) => n.id === "container:act")!.measured).toBeUndefined();
  });

  it("renders a single box for a card whose container is a top-level act (no chapter)", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("act", "Act I")], cards: [card("c1", { container: "act", scene: "s1" })] }),
    );
    // Only the act box — the card is a direct child of the act, no nested chapter.
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["container:act"]);
    expect(cardNodes(nodes)[0].position).toEqual({ x: CONTAINER_PAD, y: CONTAINER_HEADER + CONTAINER_PAD });
    expect(nodes.find((n) => n.id === "container:act")!.position).toEqual({ x: 0, y: 0 });
  });

  it("wraps both a nested chapter box and a direct act-card in the act box", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        cards: [card("inChap", { container: "chap", scene: "s1" }), card("inAct", { container: "act", scene: "s2" })],
      }),
    );
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["container:act", "container:chap"]);
    const act = nodes.find((n) => n.id === "container:act")!;
    const chap = nodes.find((n) => n.id === "container:chap")!;
    const inAct = nodes.find((n) => n.id === "inAct")!;
    const encloses = (outer: (typeof nodes)[number], x: number, y: number, w: number, h: number) =>
      outer.position.x <= x &&
      outer.position.y <= y &&
      x + w <= outer.position.x + outer.width! &&
      y + h <= outer.position.y + outer.height!;
    // The act box must enclose BOTH its chapter box and its own direct card (the
    // rect-union path — neither source may be dropped).
    expect(encloses(act, chap.position.x, chap.position.y, chap.width!, chap.height!)).toBe(true);
    expect(encloses(act, inAct.position.x, inAct.position.y, CARD_WIDTH, CARD_HEIGHT)).toBe(true);
    // The direct card sits below the chapter box, not overlapping it.
    expect(inAct.position.y).toBeGreaterThanOrEqual(chap.position.y + chap.height!);
    expect(dataOf(nodes, "container:act")).toMatchObject({ count: 2 });
  });

  it("collapses a middle 'part' container with no direct cards, nesting the chapter under the act", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("part", "Part A", "act"), container("chap", "Chapter 1", "part")],
        cards: [card("c1", { container: "chap", scene: "s1" })],
      }),
    );
    // The empty middle part draws no box; the chapter nests directly in the act.
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["container:act", "container:chap"]);
    expect(dataOf(nodes, "container:chap")).toMatchObject({ level: 1 });
    // The act still counts the card transitively.
    expect(dataOf(nodes, "container:act")).toMatchObject({ count: 1 });
  });

  it("floats a homeless card (no container) outside every box", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("loose", { container: null })] }));
    expect(containerNodes(nodes)).toEqual([]);
    expect(cardNodes(nodes).map((n) => n.id)).toEqual(["loose"]);
  });

  it("treats a card pointing at an unknown container as homeless (defensive)", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { container: "gone" })] }));
    expect(containerNodes(nodes)).toEqual([]);
    expect(cardNodes(nodes)).toHaveLength(1);
  });

  it("keeps act boxes in manuscript reading order", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act1", "Act I"), container("act2", "Act II")],
        cards: [card("c1", { container: "act1", scene: "s1" }), card("c2", { container: "act2", scene: "s2" })],
      }),
    );
    expect(containerNodes(nodes).map((n) => (n.data as PlotContainerData).title)).toEqual(["Act I", "Act II"]);
    // The second act stacks below the first (larger y).
    const [a1, a2] = containerNodes(nodes);
    expect(a2.position.y).toBeGreaterThan(a1.position.y);
  });

  it("derives card data: synopsis, scene-attachment, and the plotline colour (independent of container)", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("plot_a", "A", "forest")],
        containers: [container("chap", "Chapter 1")],
        cards: [
          card("attached", { plotline: "plot_a", synopsis: "she leaves", scene: "scene_1", container: "chap" }),
          card("loose", { plotline: "plot_a", scene: null, container: null }),
        ],
      }),
    );
    const attached = dataOf(nodes, "attached") as PlotCardData;
    const loose = dataOf(nodes, "loose") as PlotCardData;
    // Colour + the plotline's id/name (#863) come from the plotline whether the card
    // is in a container or homeless.
    expect(attached).toMatchObject({ synopsis: "she leaves", attached: true, color: "forest", plotlineId: "plot_a", plotlineName: "A" });
    expect(loose).toMatchObject({ attached: false, color: "forest", plotlineId: "plot_a", plotlineName: "A" });
  });

  it("gives a card with no plotline a null colour", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { plotline: null, container: "chap" })] }),
    );
    expect((dataOf(nodes, "c1") as PlotCardData).color).toBeNull();
  });

  it("sizes card nodes from the geometry constants (single source with the CSS)", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
    );
    expect(cardNodes(nodes)[0]).toMatchObject({ width: CARD_WIDTH, height: CARD_HEIGHT });
  });

  it("makes cards draggable, and containers draggable only by their header handle (#877)", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
    );
    expect(cardNodes(nodes)[0].draggable).toBe(true);
    // The box is draggable now, but grabbable ONLY via its header (dragHandle) so its
    // transparent interior still passes card drags + edges through (#877/#833).
    const box = containerNodes(nodes)[0];
    expect(box.draggable).toBe(true);
    expect(box.dragHandle).toBe(".plot-container-drag-handle");
  });

  it("applies a saved override and lets the soft box follow the moved card", () => {
    const proj = projection({
      containers: [container("chap", "Chapter 1")],
      cards: [card("moved", { container: "chap" })],
    });
    const nodes = buildBoardNodes(proj, { moved: { x: 500, y: 500 } });
    expect(cardNodes(nodes)[0].position).toEqual({ x: 500, y: 500 });
    // The chapter box re-wraps the card at its pinned spot (pad + header offset).
    expect(containerNodes(nodes)[0].position).toEqual({ x: 500 - CONTAINER_PAD, y: 500 - CONTAINER_PAD - CONTAINER_HEADER });
  });
});

describe("manual container size (#878)", () => {
  const chapProj = () =>
    projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] });
  const CONTENT_W = CARD_WIDTH + 2 * CONTAINER_PAD;
  const CONTENT_H = CARD_HEIGHT + 2 * CONTAINER_PAD + CONTAINER_HEADER;

  it("grows a container to a stored manual size and reports the auto-wrap size as the resize floor", () => {
    const nodes = buildBoardNodes(chapProj(), {}, { chap: { w: 800, h: 600 } });
    const box = containerNodes(nodes)[0];
    expect(box.width).toBe(800);
    expect(box.height).toBe(600);
    // A resize changes SIZE, never the derived top-left origin (#877 is separate).
    expect(box.position).toEqual({ x: 0, y: 0 });
    const d = box.data as PlotContainerData;
    // data.minWidth/minHeight = the pre-grow content size, the floor the handle can't cross.
    expect(d.minWidth).toBe(CONTENT_W);
    expect(d.minHeight).toBe(CONTENT_H);
    // The raw container id (the node id is `container:chap`) the resize callback keys by.
    expect(d.containerId).toBe("chap");
  });

  it("ignores a stored size smaller than the content (min-not-override: never below content)", () => {
    const nodes = buildBoardNodes(chapProj(), {}, { chap: { w: 10, h: 10 } });
    const box = containerNodes(nodes)[0];
    expect(box.width).toBe(CONTENT_W);
    expect(box.height).toBe(CONTENT_H);
  });

  it("grows the act box to wrap a manually enlarged chapter", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        cards: [card("c1", { container: "chap" })],
      }),
      {},
      { chap: { w: 900, h: 700 } },
    );
    const act = nodes.find((n) => n.id === "container:act")!;
    const chap = nodes.find((n) => n.id === "container:chap")!;
    expect(chap.width).toBe(900);
    // The act must still enclose the grown chapter (rectOfBox reads the post-grow box).
    expect(act.width!).toBeGreaterThanOrEqual(chap.position.x + chap.width!);
    expect(act.height!).toBeGreaterThanOrEqual(chap.position.y + chap.height!);
  });

  it("widens a member card's drag extent when its container is resized (#874 synergy)", () => {
    const grown = buildBoardNodes(chapProj(), {}, { chap: { w: 800, h: 600 } });
    const box = containerNodes(grown)[0];
    // The lock follows the GROWN box — the point of resize: a pinned single-card box
    // gets room for its card to move.
    expect(cardNodes(grown)[0].extent).toEqual(
      containerExtent({ x: box.position.x, y: box.position.y, w: box.width!, h: box.height! }),
    );
    // Strictly more horizontal travel than the un-resized (pinned) box.
    const tight = cardNodes(buildBoardNodes(chapProj()))[0].extent as [[number, number], [number, number]];
    const wide = cardNodes(grown)[0].extent as [[number, number], [number, number]];
    expect(wide[1][0] - wide[0][0]).toBeGreaterThan(tight[1][0] - tight[0][0]);
  });
});

describe("boardIsEmpty", () => {
  it("is empty with no cards and no plotlines", () => {
    expect(boardIsEmpty(projection())).toBe(true);
  });

  it("is NOT empty when it has cards", () => {
    expect(boardIsEmpty(projection({ cards: [card("c1")] }))).toBe(false);
  });

  it("is NOT empty when it has plotlines but no cards (ADR-0053: plotlines are nodes)", () => {
    // The S3 regression guard: an instantiated plotline on a card-less board must keep
    // the canvas rendered, not fall back to the empty hint.
    expect(boardIsEmpty(projection({ plotlines: [line("l1", "Romance")] }))).toBe(false);
  });
});

describe("reconcilePlotlineUiState (#928 — full-pane delete strands focus)", () => {
  const proj = projection({ plotlines: [line("l1", "Romance"), line("l2", "Mystery")] });

  it("keeps a focused/expanded id that still exists on the board", () => {
    const state = { focusedPlotlineId: "l1", expandedPlotlineId: "l2" };
    // Unchanged → returns the SAME object so the caller skips a no-op write.
    expect(reconcilePlotlineUiState(proj, state)).toBe(state);
  });

  it("drops a focused id whose plotline was deleted (the escape-hatch pane delete)", () => {
    const healed = reconcilePlotlineUiState(proj, { focusedPlotlineId: "gone", expandedPlotlineId: "l1" });
    expect(healed).toEqual({ focusedPlotlineId: null, expandedPlotlineId: "l1" });
  });

  it("drops an expanded id whose plotline was deleted", () => {
    const healed = reconcilePlotlineUiState(proj, { focusedPlotlineId: null, expandedPlotlineId: "gone" });
    expect(healed).toEqual({ focusedPlotlineId: null, expandedPlotlineId: null });
  });

  it("leaves a null (loading / failed) projection untouched — no transient clear", () => {
    const state = { focusedPlotlineId: "l1", expandedPlotlineId: "l2" };
    expect(reconcilePlotlineUiState(null, state)).toBe(state);
  });

  it("is a no-op when both ids are already null", () => {
    const state = { focusedPlotlineId: null, expandedPlotlineId: null };
    expect(reconcilePlotlineUiState(proj, state)).toBe(state);
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

  it("rejects non-finite coordinates (NaN/Infinity can't be placed by SvelteFlow)", () => {
    expect(
      readBoardPositions({
        positions: { nan: { x: NaN, y: 0 }, inf: { x: 1, y: Infinity }, ok: { x: 3, y: 4 } },
      } as unknown as Record<string, unknown>),
    ).toEqual({ ok: { x: 3, y: 4 } });
  });
});

describe("readBoardSizes (#878)", () => {
  it("reads well-formed per-container sizes out of the opaque layout", () => {
    expect(readBoardSizes({ sizes: { a: { w: 300, h: 200 }, b: { w: 50, h: 60 } } })).toEqual({
      a: { w: 300, h: 200 },
      b: { w: 50, h: 60 },
    });
  });

  it("degrades to no sizes for a missing / malformed layout (the board must render)", () => {
    expect(readBoardSizes({})).toEqual({});
    expect(readBoardSizes({ sizes: null } as unknown as Record<string, unknown>)).toEqual({});
  });

  it("drops non-finite or non-positive dimensions, keeping valid siblings", () => {
    // A zero/negative/NaN size can't be a valid box; a bad entry must not sink the board.
    expect(
      readBoardSizes({
        sizes: { nan: { w: NaN, h: 10 }, zero: { w: 0, h: 10 }, neg: { w: -5, h: 10 }, ok: { w: 12, h: 34 } },
      } as unknown as Record<string, unknown>),
    ).toEqual({ ok: { w: 12, h: 34 } });
  });
});

describe("containerMemberCardIds (#877 — a container drag translates these)", () => {
  const nested = () =>
    projection({
      containers: [
        container("act1", "Act I"),
        container("chap1", "Chapter 1", "act1"),
        container("chap2", "Chapter 2", "act1"),
        container("act2", "Act II"),
      ],
      cards: [
        card("inChap1", { container: "chap1" }),
        card("inChap2", { container: "chap2" }),
        card("inAct1", { container: "act1" }), // a card directly in the act, not a chapter
        card("inAct2", { container: "act2" }),
        card("loose", { container: null }),
      ],
    });

  it("returns every card TRANSITIVELY inside an act (its chapters' cards + its direct cards)", () => {
    expect(new Set(containerMemberCardIds(nested(), "act1"))).toEqual(new Set(["inChap1", "inChap2", "inAct1"]));
  });

  it("returns only a chapter's own cards, not its siblings' or the act's direct card", () => {
    expect(containerMemberCardIds(nested(), "chap1")).toEqual(["inChap1"]);
  });

  it("excludes homeless cards and cards of other acts", () => {
    const members = containerMemberCardIds(nested(), "act1");
    expect(members).not.toContain("loose");
    expect(members).not.toContain("inAct2");
  });

  it("returns none for an unknown container id (defensive)", () => {
    expect(containerMemberCardIds(nested(), "ghost")).toEqual([]);
  });

  it("skips a card pointing at an unknown container", () => {
    const proj = projection({ containers: [container("act1", "Act I")], cards: [card("c1", { container: "gone" })] });
    expect(containerMemberCardIds(proj, "act1")).toEqual([]);
  });
});

describe("containerDescendantIds (#877 — a container drag moves these boxes live)", () => {
  const tree = () =>
    projection({
      containers: [
        container("act1", "Act I"),
        container("chap1", "Chapter 1", "act1"),
        container("chap2", "Chapter 2", "act1"),
        container("act2", "Act II"),
      ],
    });

  it("returns an act's chapter boxes (strict descendants, excluding the act itself)", () => {
    expect(new Set(containerDescendantIds(tree(), "act1"))).toEqual(new Set(["chap1", "chap2"]));
  });

  it("returns none for a leaf chapter or another act", () => {
    expect(containerDescendantIds(tree(), "chap1")).toEqual([]);
    expect(containerDescendantIds(tree(), "act2")).toEqual([]);
  });
});

describe("movableNodePositions", () => {
  it("serializes only card positions raw (unrounded), excluding container boxes", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
      { c1: { x: 12.4, y: 7.6 } },
    );
    const positions = movableNodePositions(nodes);
    // Raw, not rounded — the persist threshold must match moveNodesCommand's raw
    // drag record, else a sub-pixel move records an undo step that saves nothing.
    expect(positions).toEqual({ c1: { x: 12.4, y: 7.6 } });
    // No `container:chap` key — container boxes are derived, never stored.
    expect(Object.keys(positions)).toEqual(["c1"]);
  });

  it("round-trips through readBoardPositions", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
      { c1: { x: 5, y: 6 } },
    );
    const serialized = { positions: movableNodePositions(nodes) };
    expect(readBoardPositions(serialized)).toEqual({ c1: { x: 5, y: 6 } });
  });
});

describe("overriddenNodePositions (sparse persist)", () => {
  const proj = () =>
    projection({
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { container: "chap" }), card("c2", { container: "chap" })],
    });

  it("keeps only the cards in the override set", () => {
    const nodes = buildBoardNodes(proj());
    // Only c1 is pinned; c2 derives from its container and must not be persisted.
    expect(overriddenNodePositions(nodes, new Set(["c1"]))).toHaveProperty("c1");
    expect(overriddenNodePositions(nodes, new Set(["c1"]))).not.toHaveProperty("c2");
  });

  it("is empty when nothing is overridden (a never-dragged board saves nothing)", () => {
    const nodes = buildBoardNodes(proj());
    expect(overriddenNodePositions(nodes, new Set())).toEqual({});
  });
});

describe("projectionDataKey (rebuild-on-data-change)", () => {
  const base = () =>
    projection({
      plotlines: [line("p1", "Main", "blue")],
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { plotline: "p1", synopsis: "s", container: "chap" })],
    });

  it("is stable when only the layout (positions) differs", () => {
    // A layout save must NOT change the key — else a re-open would rebuild and drop edits.
    expect(projectionDataKey(base())).toBe(projectionDataKey({ ...base(), layout: { positions: { c1: { x: 9, y: 9 } } } }));
  });

  it("changes when a card's container changes (→ reflow)", () => {
    const rehomed = projection({
      plotlines: [line("p1", "Main", "blue")],
      containers: [container("chap", "Chapter 1"), container("chap2", "Chapter 2")],
      cards: [card("c1", { plotline: "p1", synopsis: "s", container: "chap2" })],
    });
    expect(projectionDataKey(rehomed)).not.toBe(projectionDataKey(base()));
  });

  it("changes when a card is reassigned to another plotline (→ recolour)", () => {
    const reassigned = projection({
      plotlines: [line("p1", "Main", "blue"), line("p2", "Sub", "pink")],
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { plotline: "p2", synopsis: "s", container: "chap" })],
    });
    expect(projectionDataKey(reassigned)).not.toBe(projectionDataKey(base()));
  });

  it("changes when a container is renamed", () => {
    const renamed = projection({
      plotlines: [line("p1", "Main", "blue")],
      containers: [container("chap", "Chapter One")],
      cards: [card("c1", { plotline: "p1", synopsis: "s", container: "chap" })],
    });
    expect(projectionDataKey(renamed)).not.toBe(projectionDataKey(base()));
  });

  it("changes when a card's synopsis changes", () => {
    const edited = projection({
      plotlines: [line("p1", "Main", "blue")],
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { plotline: "p1", synopsis: "different", container: "chap" })],
    });
    expect(projectionDataKey(edited)).not.toBe(projectionDataKey(base()));
  });
});

describe("container lock (#873)", () => {
  // The extent is the box's INNER content region (inside the side padding, below the
  // header band) in absolute coords — xyflow clamps the card's drag into it and
  // subtracts the card's own size, so we do NOT pre-shrink here.
  it("containerExtent returns the box's inner content region", () => {
    expect(containerExtent({ x: 500, y: 300, w: 1000, h: 400 })).toEqual([
      [500 + CONTAINER_PAD, 300 + CONTAINER_HEADER + CONTAINER_PAD],
      [500 + 1000 - CONTAINER_PAD, 300 + 400 - CONTAINER_PAD],
    ]);
  });

  it("gives a chapter card the chapter box's extent (nested, not the act's)", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        cards: [card("c1", { container: "chap" })],
      }),
    );
    const chapBox = containerNodes(nodes).find((n) => n.id === "container:chap")!;
    const cardNode = cardNodes(nodes)[0];
    expect(cardNode.extent).toEqual(
      containerExtent({ x: chapBox.position.x, y: chapBox.position.y, w: chapBox.width!, h: chapBox.height! }),
    );
  });

  it("clamps the extent to the innermost box even for a card directly in an act", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("act", "Act I")], cards: [card("c1", { container: "act", scene: "s1" })] }),
    );
    const actBox = containerNodes(nodes)[0];
    expect(cardNodes(nodes)[0].extent).toEqual(
      containerExtent({ x: actBox.position.x, y: actBox.position.y, w: actBox.width!, h: actBox.height! }),
    );
  });

  it("leaves a homeless card free (no extent → no lock)", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("loose", { container: null })] }));
    expect(cardNodes(nodes)[0].extent).toBeUndefined();
  });

  it("treats a card pointing at an unknown container as homeless (no extent)", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("ghost", { container: "gone" })] }));
    expect(cardNodes(nodes)[0].extent).toBeUndefined();
  });

  it("pins a single-card box: the extent leaves exactly the card's own footprint", () => {
    // A chapter with one card — its box hugs the card, so the content region is the
    // card's own footprint: xyflow subtracts CARD_WIDTH/HEIGHT → min == max → pinned.
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("solo", { container: "chap" })] }),
    );
    const [[minX, minY], [maxX, maxY]] = cardNodes(nodes)[0].extent as [[number, number], [number, number]];
    expect(maxX - minX).toBe(CARD_WIDTH); // exactly the card's width of travel, all consumed by the size subtraction
    expect(maxY - minY).toBe(CARD_HEIGHT);
  });

  it("a multi-card box gives real drag room spanning its cards (the feature's point)", () => {
    // Two cards in a chapter → the box wraps both, so the extent spans the sibling
    // row: after xyflow subtracts CARD_WIDTH the card can travel CARD_GAP_X + a card
    // width. Guards against a too-tight extent (clamping to one card, or off-by-PAD)
    // that would pin every card — which the single-card test alone wouldn't catch.
    const nodes = buildBoardNodes(
      projection({
        containers: [container("chap", "Chapter 1")],
        cards: [card("a", { container: "chap" }), card("b", { container: "chap" })],
      }),
    );
    const extents = cardNodes(nodes).map((n) => n.extent as [[number, number], [number, number]]);
    // Both cards clamp to the SAME chapter box.
    expect(extents[0]).toEqual(extents[1]);
    const [[minX], [maxX]] = extents[0];
    // The extent spans two cards + the inter-card gap (well beyond the single-card
    // pin, so there is genuine horizontal travel once the card size is subtracted).
    expect(maxX - minX).toBe(2 * CARD_WIDTH + CARD_GAP_X);
    expect(maxX - minX).toBeGreaterThan(CARD_WIDTH);
  });
});

describe("plotline nodes (ADR-0053 §3)", () => {
  it("emits one draggable plotPlotline node per plotline, carrying its beats", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [
          line("p1", "Main", "blue", [{ beat_id: "b1", title: "Setup" }]),
          line("p2", "Romance", "rose", []),
        ],
      }),
    );
    const lines = plotlineNodes(nodes);
    expect(lines.map((n) => n.id)).toEqual(["p1", "p2"]);
    expect(lines[0].draggable).toBe(true);
    expect(lines[0].data).toEqual({
      title: "Main",
      color: "blue",
      beats: [{ beat_id: "b1", title: "Setup", use_count: 0 }],
    });
    expect(lines[1].data).toEqual({ title: "Romance", color: "rose", beats: [] });
  });

  it("lays plotline nodes out in a band below every card + container", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("p1", "Main")],
        containers: [container("chap", "Chapter 1")],
        cards: [card("c1", { container: "chap" }), card("loose", { container: null })],
      }),
    );
    const plY = plotlineNodes(nodes)[0].position.y;
    const others = nodes.filter((n) => n.type !== "plotPlotline");
    for (const n of others) expect(plY).toBeGreaterThan(n.position.y);
  });

  it("a saved override wins over the derived band slot", () => {
    const nodes = buildBoardNodes(projection({ plotlines: [line("p1", "Main")] }), { p1: { x: 42, y: 99 } });
    expect(plotlineNodes(nodes)[0].position).toEqual({ x: 42, y: 99 });
  });

  it("persists plotline positions (dragged) alongside cards, sparse by override", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("p1", "Main")],
        containers: [container("chap", "Chapter 1")],
        cards: [card("c1", { container: "chap" })],
      }),
    );
    // A plotline node's position is collected by the shared serializer…
    expect(movableNodePositions(nodes)).toHaveProperty("p1");
    // …and persists only when overridden (dragged this session / already saved).
    expect(overriddenNodePositions(nodes, new Set(["p1"]))).toHaveProperty("p1");
    expect(overriddenNodePositions(nodes, new Set(["c1"]))).not.toHaveProperty("p1");
  });

  it("changes the data-key when a plotline's beat roster changes (→ reflow)", () => {
    const withBeat = projection({ plotlines: [line("p1", "Main", "blue", [{ beat_id: "b1", title: "Setup" }])] });
    const renamedBeat = projection({ plotlines: [line("p1", "Main", "blue", [{ beat_id: "b1", title: "Opening" }])] });
    expect(projectionDataKey(withBeat)).not.toBe(projectionDataKey(renamedBeat));
  });

  it("changes the data-key when a beat's use-count changes (→ the node re-renders the count; S5a)", () => {
    const zero = projection({ plotlines: [line("p1", "Main", "blue", [{ beat_id: "b1", title: "Setup", use_count: 0 }])] });
    const one = projection({ plotlines: [line("p1", "Main", "blue", [{ beat_id: "b1", title: "Setup", use_count: 1 }])] });
    expect(projectionDataKey(zero)).not.toBe(projectionDataKey(one));
  });
});
