// Pure-logic test for the plot-board layout (ADR-0048 S7 Slice 4). The SvelteFlow
// canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the board's real logic — container grouping, nesting, positions, and the derived
// card/container data — is verified here (node env, no DOM); the custom nodes carry
// their own mount tests, and the composition is browser-checked.
import { describe, expect, it } from "vitest";
import {
  buildBoardNodes,
  cardPositionsFromNodes,
  overriddenCardPositions,
  projectionDataKey,
  readBoardPositions,
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

const line = (id: string, title: string, color: string | null = null) => ({ id, title, color });
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
  ...over,
});

const containerNodes = (nodes: ReturnType<typeof buildBoardNodes>) => nodes.filter((n) => n.type === "plotContainer");
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
    // Colour comes from the plotline whether the card is in a container or homeless.
    expect(attached).toMatchObject({ synopsis: "she leaves", attached: true, color: "forest" });
    expect(loose).toMatchObject({ attached: false, color: "forest" });
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

  it("makes cards draggable (S7c layout editing) and keeps container boxes fixed", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
    );
    expect(cardNodes(nodes)[0].draggable).toBe(true);
    expect(containerNodes(nodes)[0].draggable).toBe(false);
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

describe("cardPositionsFromNodes", () => {
  it("serializes only card positions raw (unrounded), excluding container boxes", () => {
    const nodes = buildBoardNodes(
      projection({ containers: [container("chap", "Chapter 1")], cards: [card("c1", { container: "chap" })] }),
      { c1: { x: 12.4, y: 7.6 } },
    );
    const positions = cardPositionsFromNodes(nodes);
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
    const serialized = { positions: cardPositionsFromNodes(nodes) };
    expect(readBoardPositions(serialized)).toEqual({ c1: { x: 5, y: 6 } });
  });
});

describe("overriddenCardPositions (sparse persist)", () => {
  const proj = () =>
    projection({
      containers: [container("chap", "Chapter 1")],
      cards: [card("c1", { container: "chap" }), card("c2", { container: "chap" })],
    });

  it("keeps only the cards in the override set", () => {
    const nodes = buildBoardNodes(proj());
    // Only c1 is pinned; c2 derives from its container and must not be persisted.
    expect(overriddenCardPositions(nodes, new Set(["c1"]))).toHaveProperty("c1");
    expect(overriddenCardPositions(nodes, new Set(["c1"]))).not.toHaveProperty("c2");
  });

  it("is empty when nothing is overridden (a never-dragged board saves nothing)", () => {
    const nodes = buildBoardNodes(proj());
    expect(overriddenCardPositions(nodes, new Set())).toEqual({});
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
