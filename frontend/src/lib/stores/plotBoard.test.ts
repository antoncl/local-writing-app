// Plot-board store (#757) — the in-flight guard that lets the menu opener and
// PlotBoardPane's restore-refresh both call refreshPlotBoard without a double
// fetch. Pure logic, node env.
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import {
  clearPlotBoard,
  createCard,
  detachCardScene,
  plotBoardStore,
  realizeCard,
  reassignCardPlotline,
  refreshPlotBoard,
  saveCardSynopsis,
  savePlotBoardLayout,
  seedCardsFromManuscript,
} from "./plotBoard";
import type { CardEntry, PlotBoard, PlotBoardProjection } from "@/lib/types";

const projection = (): PlotBoardProjection => ({
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  containers: [],
  cards: [],
});

afterEach(() => {
  clearPlotBoard();
  vi.restoreAllMocks();
});

describe("refreshPlotBoard", () => {
  it("fetches the projection into the store", async () => {
    const spy = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await refreshPlotBoard();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(get(plotBoardStore)).not.toBeNull();
  });

  it("collapses concurrent refreshes into one request", async () => {
    let resolve!: (v: PlotBoardProjection) => void;
    const spy = vi
      .spyOn(api, "getPlotBoardProjection")
      .mockImplementation(() => new Promise<PlotBoardProjection>((r) => (resolve = r)));
    const a = refreshPlotBoard();
    const b = refreshPlotBoard();
    expect(spy).toHaveBeenCalledTimes(1);
    resolve(projection());
    await Promise.all([a, b]);
    expect(get(plotBoardStore)).not.toBeNull();
  });

  it("allows a fresh fetch once the previous one settles", async () => {
    const spy = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await refreshPlotBoard();
    await refreshPlotBoard();
    expect(spy).toHaveBeenCalledTimes(2);
  });
});

describe("savePlotBoardLayout", () => {
  const board = (revision: string): PlotBoard => ({
    id: "b",
    title: "Board",
    revision,
    entry_type: "plot:board",
    layout: {},
  });

  it("PUTs the layout with the optimistic base and returns the advanced revision", async () => {
    const spy = vi.spyOn(api, "savePlotBoard").mockResolvedValue(board("r2"));
    const next = await savePlotBoardLayout({ positions: { c1: { x: 1, y: 2 } } }, "r1");
    expect(spy).toHaveBeenCalledWith({ base_revision: "r1", layout: { positions: { c1: { x: 1, y: 2 } } } });
    expect(next).toBe("r2");
  });

  it("does not touch the store (the editor owns the live revision)", async () => {
    vi.spyOn(api, "savePlotBoard").mockResolvedValue(board("r2"));
    await savePlotBoardLayout({ positions: {} }, "r1");
    expect(get(plotBoardStore)).toBeNull();
  });
});

describe("card content ops", () => {
  const card = (metadata: CardEntry["metadata"] = {}): CardEntry => ({
    id: "c1",
    title: "The letter",
    body: "",
    revision: "cr1",
    entry_type: "plot:card",
    metadata,
    computed_metadata: {},
  });

  it("realizeCard mints/attaches, then refetches the projection", async () => {
    const realize = vi.spyOn(api, "realizeCard").mockResolvedValue(card());
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await realizeCard("c1", "chap1");
    expect(realize).toHaveBeenCalledWith("c1", "chap1");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("createCard creates a card, refetches, and returns the new id", async () => {
    const create = vi.spyOn(api, "createCard").mockResolvedValue(card());
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    const id = await createCard("New card");
    expect(create).toHaveBeenCalledWith("New card");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(id).toBe("c1");
  });

  it("createCard forces a fresh fetch, not coalescing with a pre-create read-refresh", async () => {
    vi.spyOn(api, "createCard").mockResolvedValue(card());
    const stale = projection(); // the read-refresh's result: started BEFORE the create, 0 cards
    const withCard: PlotBoardProjection = {
      ...projection(),
      cards: [{ id: "c1", title: "New card", synopsis: "", plotline: null, scene: null, container: null }],
    };
    const fetchSpy = vi
      .spyOn(api, "getPlotBoardProjection")
      .mockResolvedValueOnce(stale) // 1st: the in-flight read-refresh (pre-create)
      .mockResolvedValueOnce(withCard); // 2nd: the forced post-create fetch
    const readRefresh = refreshPlotBoard(); // in flight before the mutation
    await createCard("New card"); // must NOT piggyback on the stale read — forces a 2nd fetch
    await readRefresh;
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    // The store lands on the post-create projection, not the stale one.
    expect(get(plotBoardStore)?.cards.length).toBe(1);
  });

  it("seedCardsFromManuscript seeds, then refetches", async () => {
    const seed = vi.spyOn(api, "seedFromManuscript").mockResolvedValue({ entries: [] });
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await seedCardsFromManuscript();
    expect(seed).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("detachCardScene saves the card with the scene ref dropped", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1", scene: "scene9" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await detachCardScene("c1");
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" });
  });

  it("saveCardSynopsis saves the new body, metadata untouched", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await saveCardSynopsis("c1", "a fresh synopsis");
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][1]).toBe("a fresh synopsis");
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" });
  });

  it("reassignCardPlotline sets the plotline ref, then refetches", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1", scene: "sc" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await reassignCardPlotline("c1", "p2");
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p2", scene: "sc" });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reassignCardPlotline with an empty id clears the plotline (→ Unassigned)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1", scene: "sc" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await reassignCardPlotline("c1", "");
    expect(save.mock.calls[0][0].metadata).toEqual({ scene: "sc" });
  });
});
