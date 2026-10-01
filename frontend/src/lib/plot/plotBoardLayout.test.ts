// Pure-logic test for the plot-board layout (ADR-0048 S7 Slice 4). The SvelteFlow
// canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the board's real logic — container grouping, nesting, positions, and the derived
// card/container data — is verified here (node env, no DOM); the custom nodes carry
// their own mount tests, and the composition is browser-checked.
import { describe, expect, it, beforeEach } from "vitest";
import {
  boardIsEmpty,
  buildBoardNodes,
  movableNodePositions,
  overriddenNodePositions,
  projectionDataKey,
  readBoardPositions,
  reconcilePlotlineUiState,
  reconcileArcUiState,
  reconcileCardUiState,
  CARD_GAP_X,
  CARD_HEIGHT,
  CARD_WIDTH,
  CARDS_PER_ROW,
  CONTAINER_GAP,
  freeSpotNear,
  occupiedAfterPin,
  CONTAINER_HEADER,
  CARD_SYNOPSIS_MAX_LINES,
  CARD_SYNOPSIS_LINE_H,
  CARD_SYNOPSIS_CHARS_PER_LINE,
  CARD_PILL_ROW_H,
  estCardHeight,
  pageStatusOf,
  CONTAINER_PAD,
  PLOTLINE_WIDTH,
  type PlotCardData,
  type PlotBoardNode,
  type PlotContainerData,
} from "./plotBoardLayout";
import { setPalette } from "@/lib/utils/colors";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { PlotBoardProjection } from "@/lib/types";

function projection(over: Partial<PlotBoardProjection> = {}): PlotBoardProjection {
  return {
    board_id: "board_1",
    board_revision: "r1",
    layout: {},
    plotlines: [],
    arcs: [],
    containers: [],
    decks: [],
    cards: [],
    diagnostics: [],
    ...over,
  };
}

const arc = (
  id: string,
  title: string,
  over: Partial<PlotBoardProjection["arcs"][number]> = {},
): PlotBoardProjection["arcs"][number] => ({
  id,
  title,
  color: null,
  character_id: null,
  character_name: null,
  character_initial: null,
  beats: [],
  ...over,
});

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
  deck: null,
  planned_in: null,
  planned_after: null,
  container_order: null,
  page_status: null,
  beats: [],
  sequence: null,
  causal_links: [],
  story_order: 0,
  story_movable: true,
  ...over,
});

const containerNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotContainer");
const plotlineNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotPlotline");
const arcNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotArc");
const cardNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotCard");
const dataOf = (nodes: ReturnType<typeof buildBoardNodes>, id: string) => nodes.find((n) => n.id === id)!.data;

// The arc colour resolution reads the machine palette + lore roster global stores
// directly (buildBoardNodes' one store-backed exception — mirrors the ReferencePicker/
// plotline-roster precedent). Reset both between tests so no test's palette/roster
// leaks into the next.
beforeEach(() => {
  setPalette([]);
  loreEntriesStore.set([]);
});

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

  // ADR-0094 §9: one nested box per level. A sequence holding cards draws inside its
  // chapter's box, inside its act's, even though the chapter holds no card directly.
  it("nests one box per level, each inside its parent's", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act"), container("seq", "Sequence 1", "chap")],
        cards: [card("c1", { container: "seq", scene: "s1" })],
      }),
    );
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["container:act", "container:chap", "container:seq"]);
    expect(containerNodes(nodes).map((n) => (n.data as PlotContainerData).level)).toEqual([0, 1, 2]);
    // Every box counts the card transitively.
    expect(containerNodes(nodes).map((n) => (n.data as PlotContainerData).count)).toEqual([1, 1, 1]);
    const inside = (inner: PlotBoardNode, outer: PlotBoardNode) =>
      inner.position.x > outer.position.x &&
      inner.position.y > outer.position.y &&
      inner.position.x + inner.width! < outer.position.x + outer.width! &&
      inner.position.y + inner.height! < outer.position.y + outer.height!;
    const [act, chap, seq] = containerNodes(nodes);
    const c1 = cardNodes(nodes)[0];
    expect(inside(seq, chap)).toBe(true);
    expect(inside(chap, act)).toBe(true);
    expect(inside(c1, seq)).toBe(true);
    // Deeper boxes stack above their parents, and every card above every box.
    expect([act.zIndex, chap.zIndex, seq.zIndex]).toEqual([0, 1, 2]);
    expect(c1.zIndex).toBeGreaterThan(seq.zIndex!);
  });

  it("wraps a box's child boxes and its own direct cards without overlap", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        cards: [card("c1", { container: "chap", scene: "s1" }), card("c2", { container: "act", scene: "s2" })],
      }),
    );
    const chap = containerNodes(nodes).find((n) => n.id === "container:chap")!;
    const act = containerNodes(nodes).find((n) => n.id === "container:act")!;
    const direct = cardNodes(nodes).find((n) => n.id === "c2")!;
    // The act's direct card sits below its chapter box, still inside the act.
    expect(direct.position.y).toBeGreaterThanOrEqual(chap.position.y + chap.height!);
    expect(direct.position.y + CARD_HEIGHT).toBeLessThan(act.position.y + act.height!);
  });

  it("flows a card with no container or deck into the Loose cards box", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("orphan", { container: null })] }));
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["loose"]);
    expect(dataOf(nodes, "loose")).toMatchObject({ boxKind: "loose", title: "Loose cards", cardIds: ["orphan"], count: 1 });
    expect(cardNodes(nodes).map((n) => n.id)).toEqual(["orphan"]);
  });

  it("carries story time onto the card: swap anchors, movability and the late causes (ADR-0097 §8)", () => {
    const nodes = buildBoardNodes(
      projection({
        cards: [
          card("a", { title: "A", story_order: 0 }),
          card("b", { title: "B", story_order: 1, causal_links: ["a"] }),
          card("x", { story_order: 2, story_movable: false }),
        ],
      }),
    );
    expect(dataOf(nodes, "a")).toMatchObject({
      storyMovable: true,
      storyEarlier: null,
      storyLater: { after_id: "b" },
      lateCauses: ["B"], // B leads to A yet comes after it
    });
    expect(dataOf(nodes, "b")).toMatchObject({ storyEarlier: { before_id: "a" }, storyLater: null, lateCauses: [] });
    expect(dataOf(nodes, "x")).toMatchObject({ storyMovable: false, storyEarlier: null, storyLater: null });
  });

  it("treats a card pointing at an unknown container as loose (defensive)", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { container: "gone" })] }));
    expect(containerNodes(nodes).map((n) => n.id)).toEqual(["loose"]);
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
          card("free", { plotline: "plot_a", scene: null, container: null }),
        ],
      }),
    );
    const attached = dataOf(nodes, "attached") as PlotCardData;
    const free = dataOf(nodes, "free") as PlotCardData;
    // Colour + the plotline's id/name (#863) come from the plotline whether the card
    // is in a container or loose.
    expect(attached).toMatchObject({ synopsis: "she leaves", attached: true, color: "forest", plotlineId: "plot_a", plotlineName: "A" });
    expect(free).toMatchObject({ attached: false, color: "forest", plotlineId: "plot_a", plotlineName: "A" });
  });

  it("flags a card planned in a chapter, with no scene, as planned", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("chap", "Chapter 1")],
        cards: [
          card("plan", { container: "chap", planned_in: "chap", planned_after: "scene_0" }),
          card("written", { container: "chap", scene: "scene_1" }),
          card("free", {}),
        ],
      }),
    );
    expect(dataOf(nodes, "plan")).toMatchObject({ planned: true, plannedAfter: "scene_0", sceneId: null });
    expect(dataOf(nodes, "written")).toMatchObject({ planned: false, plannedAfter: null, sceneId: "scene_1" });
    expect((dataOf(nodes, "free") as PlotCardData).planned).toBe(false);
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

  it("makes cards draggable, but only by their grip handle (#876), and containers only by their header handle (#877)", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
    );
    // A card drags ONLY by its leading grip (dragHandle), so its control-dense body stays
    // free for inline edits (#876) — the whole-body drag surface was near-ungrabbable.
    const cardNode = cardNodes(nodes)[0];
    expect(cardNode.draggable).toBe(true);
    expect(cardNode.dragHandle).toBe(".plot-card-drag-handle");
    // The box is draggable now, but grabbable ONLY via its header (dragHandle) so its
    // transparent interior still passes card drags + edges through (#877/#833).
    const box = containerNodes(nodes)[0];
    expect(box.draggable).toBe(true);
    expect(box.dragHandle).toBe(".plot-container-drag-handle");
  });

  it("honours a stored top-level box position and carries its cards with it", () => {
    const proj = projection({
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { container: "chap" })],
    });
    const nodes = buildBoardNodes(proj, { "container:chap": { x: 500, y: 500 } });
    expect(containerNodes(nodes)[0].position).toEqual({ x: 500, y: 500 });
    // The card takes its slot inside the moved box (pad + header offset).
    expect(cardNodes(nodes)[0].position).toEqual({ x: 500 + CONTAINER_PAD, y: 500 + CONTAINER_HEADER + CONTAINER_PAD });
  });

  it("ignores a stored card position: a card always flows in its box", () => {
    const proj = projection({
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { container: "chap" })],
    });
    const flowed = cardNodes(buildBoardNodes(proj))[0].position;
    expect(cardNodes(buildBoardNodes(proj, { c1: { x: 500, y: 500 } }))[0].position).toEqual(flowed);
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

describe("movableNodePositions", () => {
  it("serializes the placed nodes raw (unrounded): top-level boxes, never cards or nested boxes", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("act", "Act I"), container("chap", "Chapter 1", "act")],
        // A written card: no unwritten card, so no loose box (#2399) to store either.
        cards: [card("c1", { container: "chap", scene: "s1" })],
      }),
      { "container:act": { x: 12.4, y: 7.6 } },
    );
    const positions = movableNodePositions(nodes);
    // Raw, not rounded — the persist threshold must match moveNodesCommand's raw
    // drag record, else a sub-pixel move records an undo step that saves nothing.
    expect(positions).toEqual({ "container:act": { x: 12.4, y: 7.6 } });
    // No card and no nested chapter box: they flow, so nothing of theirs is stored.
    expect(Object.keys(positions)).toEqual(["container:act"]);
  });

  it("round-trips through readBoardPositions", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap", scene: "s1" })] }),
      { "container:chap": { x: 5, y: 6 } },
    );
    const serialized = { positions: movableNodePositions(nodes) };
    expect(readBoardPositions(serialized)).toEqual({ "container:chap": { x: 5, y: 6 } });
  });
});

describe("overriddenNodePositions (sparse persist)", () => {
  const proj = () =>
    projection({
      containers: [container("a", "Act I"), container("b", "Act II")],
      cards: [card("c1", { container: "a" }), card("c2", { container: "b" })],
    });

  it("keeps only the boxes in the override set", () => {
    const nodes = buildBoardNodes(proj());
    // Only act I is placed; act II derives its slot in the stack and must not be persisted.
    expect(overriddenNodePositions(nodes, new Set(["container:a"]))).toHaveProperty(["container:a"]);
    expect(overriddenNodePositions(nodes, new Set(["container:a"]))).not.toHaveProperty(["container:b"]);
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

  // #2397: a drag inside ONE chapter changes only where the card sits in it — the key
  // must still change, or the board keeps the old order until some other edit.
  it.each([
    ["container_order", { container_order: 3.5 }],
    ["planned_in", { planned_in: "chap" }],
    ["planned_after", { planned_after: "scene_9" }],
    ["sequence", { sequence: 4 }],
  ])("changes when only a card's %s changes (→ re-sort within its box)", (_field, overrides) => {
    const moved = projection({
      plotlines: [line("p1", "Main", "blue")],
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { plotline: "p1", synopsis: "s", container: "chap", ...overrides })],
    });
    expect(projectionDataKey(moved)).not.toBe(projectionDataKey(base()));
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
    // Draggable, but only by its grip handle — the same one a card uses (#876), so every
    // card-like node drags identically and the header's expand/focus controls stay click-only.
    expect(lines[0].draggable).toBe(true);
    expect(lines[0].dragHandle).toBe(".plot-card-drag-handle");
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

describe("character-arc nodes (ADR-0080 §5 / Amendment 1)", () => {
  it("emits one draggable plotArc node per arc, carrying its beats + bound character", () => {
    const nodes = buildBoardNodes(
      projection({
        arcs: [
          arc("a1", "Elena's redemption", { character_id: "char_1", character_name: "Elena", character_initial: "E", beats: [{ beat_id: "b1", title: "Denial", use_count: 0 }] }),
          arc("a2", "Marcus's fall"),
        ],
      }),
    );
    const arcs = arcNodes(nodes);
    expect(arcs.map((n) => n.id)).toEqual(["a1", "a2"]);
    // Draggable by the same leading grip as a card/plotline (#876).
    expect(arcs[0].draggable).toBe(true);
    expect(arcs[0].dragHandle).toBe(".plot-card-drag-handle");
    expect(arcs[0].data).toMatchObject({
      title: "Elena's redemption",
      color: null,
      beats: [{ beat_id: "b1", title: "Denial", use_count: 0 }],
      characterId: "char_1",
      characterName: "Elena",
      characterInitial: "E",
    });
  });

  it("lays arc nodes out in a band BELOW the plotline band", () => {
    const nodes = buildBoardNodes(
      projection({
        plotlines: [line("p1", "Main")],
        arcs: [arc("a1", "Elena's redemption")],
      }),
    );
    const plY = plotlineNodes(nodes)[0].position.y;
    const arcY = arcNodes(nodes)[0].position.y;
    expect(arcY).toBeGreaterThan(plY);
  });

  it("still bands below every card/container/plotline when there are no plotlines", () => {
    const nodes = buildBoardNodes(
      projection({
        containers: [container("chap", "Chapter 1")],
        cards: [card("c1", { container: "chap" })],
        arcs: [arc("a1", "Elena's redemption")],
      }),
    );
    const arcY = arcNodes(nodes)[0].position.y;
    const others = nodes.filter((n) => n.type !== "plotArc");
    for (const n of others) expect(arcY).toBeGreaterThan(n.position.y);
  });

  it("a saved override wins over the derived band slot", () => {
    const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "Elena's redemption")] }), { a1: { x: 7, y: 8 } });
    expect(arcNodes(nodes)[0].position).toEqual({ x: 7, y: 8 });
  });

  it("spaces sibling arcs the same PLOTLINE_WIDTH + gap as plotline nodes", () => {
    const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "One"), arc("a2", "Two")] }));
    const [n1, n2] = arcNodes(nodes);
    expect(n2.position.x - n1.position.x).toBe(PLOTLINE_WIDTH + CARD_GAP_X);
  });

  it("persists arc positions (dragged) alongside cards/plotlines, sparse by override", () => {
    const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "Elena's redemption")] }));
    expect(movableNodePositions(nodes)).toHaveProperty("a1");
    expect(overriddenNodePositions(nodes, new Set(["a1"]))).toHaveProperty("a1");
    expect(overriddenNodePositions(nodes, new Set())).not.toHaveProperty("a1");
  });

  describe("colour resolution (Amendment 1 §1): own → bound character's → the lore kind default", () => {
    it("uses the arc's OWN colour when set, even with a bound character", () => {
      setPalette([
        { id: "rose", label: "Rose", hex: "#b0567a" },
        { id: "moss", label: "Moss", hex: "#5a7a4a" },
      ]);
      loreEntriesStore.set([{ id: "char_1", title: "Elena", body: "", entry_type: "lore:character", metadata: { color: "moss" } }]);
      const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "Elena's redemption", { color: "rose", character_id: "char_1" })] }));
      expect((arcNodes(nodes)[0].data as { resolvedColorHex: string | null }).resolvedColorHex).toBe("#b0567a");
    });

    it("falls back to the bound character's colour when the arc has none", () => {
      setPalette([{ id: "moss", label: "Moss", hex: "#5a7a4a" }]);
      loreEntriesStore.set([{ id: "char_1", title: "Elena", body: "", entry_type: "lore:character", metadata: { color: "moss" } }]);
      const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "Elena's redemption", { character_id: "char_1" })] }));
      expect((arcNodes(nodes)[0].data as { resolvedColorHex: string | null }).resolvedColorHex).toBe("#5a7a4a");
    });

    it("falls back to the lore kind default when the arc is unbound and colourless", () => {
      setPalette([{ id: "slate-blue", label: "Slate blue", hex: "#4a6a8a" }]);
      const nodes = buildBoardNodes(projection({ arcs: [arc("a1", "Untitled")] }));
      // resolveColorForKind("lore") — the KIND_DEFAULT_SWATCH mapping (colors.ts).
      expect((arcNodes(nodes)[0].data as { resolvedColorHex: string | null }).resolvedColorHex).toBe("#4a6a8a");
    });
  });
});

describe("card-beat colour denormalisation (ADR-0080 slice 3b-ii)", () => {
  const rawBeat = (over: Partial<PlotBoardProjection["cards"][number]["beats"][number]> = {}) => ({
    plotline_id: "line_1",
    plotline_title: "Main",
    plotline_color: null,
    beat_id: "b1",
    title: "Setup",
    number: 1,
    holder_kind: "plot:plotline",
    character_id: null,
    character_name: null,
    character_initial: null,
    ...over,
  });

  it("gives an event-beat its resolvedColorHex from the plotline swatch", () => {
    setPalette([{ id: "rose", label: "Rose", hex: "#b0567a" }]);
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { beats: [rawBeat({ plotline_color: "rose" })] })] }));
    expect((dataOf(nodes, "c1") as PlotCardData).beats[0].resolvedColorHex).toBe("#b0567a");
  });

  it("gives an event-beat a null resolvedColorHex when the plotline is colourless", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { beats: [rawBeat({ plotline_color: null })] })] }));
    expect((dataOf(nodes, "c1") as PlotCardData).beats[0].resolvedColorHex).toBeNull();
  });

  it("gives a change-beat its resolvedColorHex from its arc's OWN colour", () => {
    setPalette([{ id: "rose", label: "Rose", hex: "#b0567a" }]);
    const nodes = buildBoardNodes(
      projection({
        arcs: [arc("a1", "Elena's redemption", { color: "rose" })],
        cards: [card("c1", { beats: [rawBeat({ plotline_id: "a1", holder_kind: "plot:character_arc" })] })],
      }),
    );
    expect((dataOf(nodes, "c1") as PlotCardData).beats[0].resolvedColorHex).toBe("#b0567a");
  });

  it("falls back to the bound character's colour for a change-beat when the arc has none", () => {
    setPalette([{ id: "moss", label: "Moss", hex: "#5a7a4a" }]);
    loreEntriesStore.set([{ id: "char_1", title: "Elena", body: "", entry_type: "lore:character", metadata: { color: "moss" } }]);
    const nodes = buildBoardNodes(
      projection({
        arcs: [arc("a1", "Elena's redemption", { character_id: "char_1" })],
        cards: [card("c1", { beats: [rawBeat({ plotline_id: "a1", holder_kind: "plot:character_arc" })] })],
      }),
    );
    expect((dataOf(nodes, "c1") as PlotCardData).beats[0].resolvedColorHex).toBe("#5a7a4a");
  });
});

describe("boardIsEmpty (arcs)", () => {
  it("is NOT empty when it has arcs but no cards/plotlines (ADR-0080: an arc is a node too)", () => {
    expect(boardIsEmpty(projection({ arcs: [arc("a1", "Elena's redemption")] }))).toBe(false);
  });
});

describe("projectionDataKey (arcs)", () => {
  it("changes when an arc's own colour changes", () => {
    const before = projection({ arcs: [arc("a1", "Elena's redemption", { color: null })] });
    const after = projection({ arcs: [arc("a1", "Elena's redemption", { color: "rose" })] });
    expect(projectionDataKey(before)).not.toBe(projectionDataKey(after));
  });

  it("changes when an arc is rebound to a different character", () => {
    const before = projection({ arcs: [arc("a1", "Elena's redemption", { character_id: "char_1" })] });
    const after = projection({ arcs: [arc("a1", "Elena's redemption", { character_id: "char_2" })] });
    expect(projectionDataKey(before)).not.toBe(projectionDataKey(after));
  });

  it("changes when a card's beat holder_kind or character_id changes (rebind rehydrates the pill)", () => {
    const eventBeat = { plotline_id: "x", plotline_title: "", plotline_color: null, beat_id: "b1", title: "", number: 1, holder_kind: "plot:plotline", character_id: null, character_name: null, character_initial: null };
    const changeBeat = { ...eventBeat, holder_kind: "plot:character_arc", character_id: "char_1" };
    const before = projection({ cards: [card("c1", { beats: [eventBeat] })] });
    const after = projection({ cards: [card("c1", { beats: [changeBeat] })] });
    expect(projectionDataKey(before)).not.toBe(projectionDataKey(after));
  });
});

describe("reconcileArcUiState (mirrors reconcilePlotlineUiState, #928)", () => {
  const proj = projection({ arcs: [arc("a1", "Elena's redemption"), arc("a2", "Marcus's fall")] });

  it("keeps an expanded id that still exists on the board", () => {
    const state = { expandedArcId: "a1" };
    expect(reconcileArcUiState(proj, state)).toBe(state);
  });

  it("drops an expanded id whose arc was deleted", () => {
    expect(reconcileArcUiState(proj, { expandedArcId: "gone" })).toEqual({ expandedArcId: null });
  });

  it("leaves a null (loading / failed) projection untouched", () => {
    const state = { expandedArcId: "a1" };
    expect(reconcileArcUiState(null, state)).toBe(state);
  });
});

describe("reconcileCardUiState (mirrors reconcilePlotlineUiState, #1920)", () => {
  const proj = projection({ cards: [card("c1"), card("c2")] });

  it("keeps a revealed id that still exists on the board", () => {
    const state = { revealedCardId: "c1" };
    expect(reconcileCardUiState(proj, state)).toBe(state);
  });

  it("drops a revealed id whose card was deleted", () => {
    expect(reconcileCardUiState(proj, { revealedCardId: "gone" })).toEqual({ revealedCardId: null });
  });

  it("leaves a null (loading / failed) projection untouched", () => {
    const state = { revealedCardId: "c1" };
    expect(reconcileCardUiState(null, state)).toBe(state);
  });
});

// #1907: a card's page-status label and swatch come from the schema's
// `page_status` options — the rail's words and colours, spelled once — and a
// sparse blank resolves to the schema default.
describe("buildBoardNodes — page status from the schema", () => {
  const withPageStatus = (options: Array<{ value: string; label?: string; color?: string }>, def = "unwritten") =>
    metadataSchemaStore.set({
      version: 1,
      entry_types: {},
      groups: {},
      fields: { page_status: { name: "Page status", type: "select", default: def, options } },
    } as never);

  it("resolves the value, label and swatch from the options; a blank reads as the default", () => {
    withPageStatus([
      { value: "unwritten", label: "Unwritten", color: "stone" },
      { value: "off_page", label: "Off the page", color: "graphite" },
      { value: "on_page", label: "On the page", color: "moss" },
    ]);
    const nodes = buildBoardNodes(
      projection({ cards: [card("blank"), card("off", { page_status: "off_page" }), card("on", { page_status: "on_page", scene: "s1" })] }),
    );
    expect(dataOf(nodes, "blank")).toMatchObject({ pageStatus: "unwritten", pageStatusLabel: "Unwritten", pageStatusSwatch: "stone" });
    expect(dataOf(nodes, "off")).toMatchObject({ pageStatus: "off_page", pageStatusLabel: "Off the page", pageStatusSwatch: "graphite" });
    expect(dataOf(nodes, "on")).toMatchObject({ pageStatus: "on_page", pageStatusLabel: "On the page", pageStatusSwatch: "moss" });
  });

  it("without the field in the schema, the value stands in for the label and there is no swatch", () => {
    metadataSchemaStore.set(null);
    const nodes = buildBoardNodes(projection({ cards: [card("c", { page_status: "off_page" })] }));
    expect(dataOf(nodes, "c")).toMatchObject({ pageStatus: "off_page", pageStatusLabel: "off_page", pageStatusSwatch: null });
  });
});

// #2348: each new card used to land one card-width further out (one unwrapped row);
// auto-laid-out cards now wrap into a grid, a pinned card gives up its slot, and a
// NEW card goes near the view centre instead.
describe("card placement (#2348)", () => {
  const STEP_X = CARD_WIDTH + CARD_GAP_X;
  const STEP_Y = CARD_HEIGHT + CONTAINER_GAP;
  const loose = (n: number) => Array.from({ length: n }, (_, i) => card(`c${i}`));
  const posOf = (nodes: ReturnType<typeof buildBoardNodes>, id: string) => nodes.find((n) => n.id === id)!.position;

  it("wraps loose cards into rows of CARDS_PER_ROW instead of one endless row", () => {
    const nodes = buildBoardNodes(projection({ cards: loose(CARDS_PER_ROW * 2 + 1) }));
    const first = posOf(nodes, "c0");
    const lastOfRow = posOf(nodes, `c${CARDS_PER_ROW - 1}`);
    const nextRow = posOf(nodes, `c${CARDS_PER_ROW}`);
    expect(lastOfRow).toEqual({ x: first.x + (CARDS_PER_ROW - 1) * STEP_X, y: first.y });
    expect(nextRow).toEqual({ x: first.x, y: first.y + STEP_Y });
    const widest = Math.max(...cardNodes(nodes).map((n) => n.position.x));
    expect(widest).toBe(first.x + (CARDS_PER_ROW - 1) * STEP_X);
  });

  it("wraps a container's own cards the same way, and the box grows to hold them", () => {
    const cards = Array.from({ length: CARDS_PER_ROW + 2 }, (_, i) => card(`k${i}`, { container: "ch" }));
    const nodes = buildBoardNodes(projection({ containers: [container("ch", "Chapter 1")], cards }));
    const first = posOf(nodes, "k0");
    expect(posOf(nodes, `k${CARDS_PER_ROW}`)).toEqual({ x: first.x, y: first.y + STEP_Y });
    const box = containerNodes(nodes)[0];
    expect(box.position.y + box.height!).toBeGreaterThanOrEqual(first.y + STEP_Y + CARD_HEIGHT);
  });

  it("a placed top-level box gives up its slot in the stack, so the others close ranks", () => {
    const containers = [container("a", "Act I"), container("b", "Act II"), container("c", "Act III")];
    const cards = [card("ca", { container: "a" }), card("cb", { container: "b" }), card("cc", { container: "c" })];
    const nodes = buildBoardNodes(projection({ containers, cards }), { "container:a": { x: 5000, y: 5000 } });
    expect(posOf(nodes, "container:a")).toEqual({ x: 5000, y: 5000 });
    // Act II takes the first slot Act I no longer holds.
    const without = buildBoardNodes(projection({ containers: containers.slice(1), cards: cards.slice(1) }));
    expect(posOf(nodes, "container:b")).toEqual(posOf(without, "container:b"));
  });

  it("puts the plotline band below the stacked boxes", () => {
    const nodes = buildBoardNodes(projection({ cards: loose(CARDS_PER_ROW + 1), plotlines: [line("p1", "Heist")] }));
    const lowestCard = Math.max(...cardNodes(nodes).map((n) => n.position.y + CARD_HEIGHT));
    expect(plotlineNodes(nodes)[0].position.y).toBeGreaterThan(lowestCard);
  });

  // The collision the real app showed: a new node, while unpinned, holds the first slot of
  // the stack and pushes an older unpinned one to the second; reading free space from THAT
  // layout freed slot 0, the new node was pinned there, and the older one slid straight
  // back onto it. Free space must be read after the pin.
  it("reads free space from the layout after the pin, so an unpinned box can't slide back under the new one", () => {
    // Deck order is by title: "new" stacks first, so unpinned it takes slot 0.
    const decks = [
      { id: "new", title: "A new deck", synopsis: "", parent: null, movable: true },
      { id: "old", title: "B old deck", synopsis: "", parent: null, movable: true },
    ];
    const slot0 = posOf(buildBoardNodes(projection({ decks: decks.slice(1) })), "deck:old");
    const naive = buildBoardNodes(projection({ decks })).filter((n) => n.id !== "deck:new");
    expect(naive.find((n) => n.id === "deck:old")!.position).not.toEqual(slot0); // "old" sits in slot 1 here
    const occupied = occupiedAfterPin(projection({ decks }), {}, "deck:new");
    expect(occupied).toContainEqual(expect.objectContaining({ x: slot0.x, y: slot0.y }));
    const center = { x: slot0.x + CARD_WIDTH / 2, y: slot0.y + CARD_HEIGHT / 2 };
    expect(freeSpotNear(center, { w: CARD_WIDTH, h: CARD_HEIGHT }, occupied)).not.toEqual(slot0);
  });

  describe("freeSpotNear", () => {
    const size = { w: CARD_WIDTH, h: CARD_HEIGHT };
    const overlaps = (at: { x: number; y: number }, b: { x: number; y: number; w: number; h: number }) =>
      at.x < b.x + b.w && b.x < at.x + size.w && at.y < b.y + b.h && b.y < at.y + size.h;

    it("centres the node on the view centre when that spot is free", () => {
      expect(freeSpotNear({ x: 1000, y: 800 }, size, [])).toEqual({ x: 1000 - CARD_WIDTH / 2, y: 800 - CARD_HEIGHT / 2 });
    });

    it("steps to the nearest free spot when the centre is taken", () => {
      const center = { x: 1000, y: 800 };
      const taken = { x: center.x - CARD_WIDTH / 2, y: center.y - CARD_HEIGHT / 2, w: CARD_WIDTH, h: CARD_HEIGHT };
      const at = freeSpotNear(center, size, [taken]);
      expect(overlaps(at, taken)).toBe(false);
      // One step away, not somewhere far off.
      expect(Math.abs(at.x - taken.x) <= STEP_X && Math.abs(at.y - taken.y) <= CARD_HEIGHT + CARD_GAP_X).toBe(true);
    });

    it("never lands on any card around a crowded centre", () => {
      const center = { x: 0, y: 0 };
      const occupied = [-1, 0, 1].flatMap((gx) =>
        [-1, 0, 1].map((gy) => ({ x: gx * STEP_X - CARD_WIDTH / 2, y: gy * STEP_Y - CARD_HEIGHT / 2, w: CARD_WIDTH, h: CARD_HEIGHT })),
      );
      const at = freeSpotNear(center, size, occupied);
      expect(occupied.some((b) => overlaps(at, b))).toBe(false);
    });
  });
});

// #2354: the synopsis is the card — a card's height follows its content, a grid row is
// as tall as its tallest card, and containers wrap the cards' real rects.
describe("per-card height (#2354)", () => {
  const long = "x".repeat(CARD_SYNOPSIS_CHARS_PER_LINE * 6);
  const posOf = (nodes: ReturnType<typeof buildBoardNodes>, id: string) => nodes.find((n) => n.id === id)!.position;

  it("an empty card measures CARD_HEIGHT; a longer synopsis is taller", () => {
    expect(estCardHeight("", "", 0)).toBe(CARD_HEIGHT);
    expect(estCardHeight("t", long, 0)).toBeGreaterThan(estCardHeight("t", "short", 0));
    expect(estCardHeight("t", "a\nb\nc", 0)).toBe(estCardHeight("t", "a", 0) + 2 * CARD_SYNOPSIS_LINE_H);
  });

  it("caps the synopsis at CARD_SYNOPSIS_MAX_LINES (the rest scrolls)", () => {
    const capped = estCardHeight("t", "y".repeat(CARD_SYNOPSIS_CHARS_PER_LINE * 100), 0);
    const atMax = estCardHeight("t", "y".repeat(CARD_SYNOPSIS_CHARS_PER_LINE * CARD_SYNOPSIS_MAX_LINES), 0);
    expect(capped).toBe(atMax);
  });

  it("beats add a foot band, growing with the pill rows", () => {
    expect(estCardHeight("t", "s", 1)).toBeGreaterThanOrEqual(estCardHeight("t", "s", 0));
    expect(estCardHeight("t", "s", 6)).toBeGreaterThan(estCardHeight("t", "s", 2));
    expect(estCardHeight("t", "s", 4) - estCardHeight("t", "s", 2)).toBe(CARD_PILL_ROW_H);
  });

  it("seeds each card node's size + measured from its own estimate", () => {
    const nodes = buildBoardNodes(projection({ cards: [card("c1", { synopsis: long })] }));
    const h = estCardHeight("c1", long, 0);
    expect(cardNodes(nodes)[0]).toMatchObject({ width: CARD_WIDTH, height: h, measured: { width: CARD_WIDTH, height: h } });
  });

  it("a grid row is as tall as its tallest card: a tall card pushes the next row down", () => {
    const cards = Array.from({ length: CARDS_PER_ROW + 1 }, (_, i) =>
      card(`c${i}`, { synopsis: i === 2 ? long : "" }),
    );
    const nodes = buildBoardNodes(projection({ cards }));
    const tall = estCardHeight("c2", long, 0);
    const y0 = posOf(nodes, "c0").y;
    for (let i = 1; i < CARDS_PER_ROW; i++) expect(posOf(nodes, `c${i}`).y).toBe(y0); // one row, one y
    expect(posOf(nodes, `c${CARDS_PER_ROW}`).y).toBe(y0 + tall + CONTAINER_GAP);
  });

  it("a container box wraps a tall card's real rect", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("ch", "Chapter 1")], cards: [card("c1", { container: "ch", synopsis: long })] }),
    );
    const box = containerNodes(nodes)[0];
    expect(box.height).toBe(estCardHeight("c1", long, 0) + 2 * CONTAINER_PAD + CONTAINER_HEADER);
  });
});

describe("pageStatusOf default flag (#2354)", () => {
  const field = {
    default: "unwritten",
    options: [{ value: "unwritten", label: "Unwritten", color: "stone" }],
  } as unknown as Parameters<typeof pageStatusOf>[1];

  it("is default for the field's default value, non-default otherwise", () => {
    expect(pageStatusOf(null, field).pageStatusIsDefault).toBe(true);
    expect(pageStatusOf("unwritten", field).pageStatusIsDefault).toBe(true);
    expect(pageStatusOf("off_page", field).pageStatusIsDefault).toBe(false);
  });

  it("is default when there is no field", () => {
    expect(pageStatusOf("off_page", undefined).pageStatusIsDefault).toBe(true);
  });
});
