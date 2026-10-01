// Plot-board store (#757) — the in-flight guard that lets the menu opener and
// PlotBoardPane's restore-refresh both call refreshPlotBoard without a double
// fetch. Pure logic, node env.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { HttpError } from "@/lib/api/core";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import {
  attachCardScene,
  heldSceneIds,
  clearPlotBoard,
  createCard,
  detachCardScene,
  deleteCard,
  plotBoardStore,
  plotBoardError,
  realizeCard,
  reassignCardPlotline,
  refreshPlotBoard,
  renameCard,
  saveCardSynopsis,
  savePlotBoardLayout,
  seedCardsFromManuscript,
  linkCardBeat,
  unlinkCardBeat,
  linkCardCausal,
  unlinkCardCausal,
  setCardPageStatus,
  cardStateOf,
  getCardState,
  restoreCardState,
  recreateCard,
  sceneReferents,
  readScene,
  deleteScene,
} from "./plotBoard";
import { structureStore } from "@/lib/stores/structure";
import type { Scene, StructureDocument } from "@/lib/types";
import type { CardEntry, PlotBoard, PlotBoardProjection } from "@/lib/types";

const projection = (): PlotBoardProjection => ({
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  arcs: [],
  containers: [],
  decks: [],
  cards: [],
  diagnostics: [],
});

// A card mutation now also refreshes the lightweight card roster (ADR-0074 slice 6:
// the context picker's plotline selectors expand over it) via refreshAfterMutation.
// Stub it so the mutation ops don't leak a real /plot/cards fetch (#973); no card-op
// assertion here concerns the card roster.
beforeEach(() => {
  vi.spyOn(api, "listCards").mockResolvedValue({ entries: [] });
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

describe("refreshPlotBoard load-error state (#756)", () => {
  it("records the failure message and leaves the projection null, without rejecting", async () => {
    vi.spyOn(api, "getPlotBoardProjection").mockRejectedValue(new Error("boom"));
    // Must not reject — the callers are `void refreshPlotBoard()`, so a rejection
    // would be an unhandled promise; the pane reads the error from the store.
    await expect(refreshPlotBoard()).resolves.toBeUndefined();
    expect(get(plotBoardStore)).toBeNull();
    expect(get(plotBoardError)).toBe("boom");
  });

  it("clears the error on a successful retry and loads the board", async () => {
    vi.spyOn(api, "getPlotBoardProjection").mockRejectedValueOnce(new Error("boom")).mockResolvedValue(projection());
    await refreshPlotBoard();
    expect(get(plotBoardError)).toBe("boom");
    await refreshPlotBoard(); // Retry
    expect(get(plotBoardError)).toBeNull();
    expect(get(plotBoardStore)).not.toBeNull();
  });

  it("clearPlotBoard resets both the projection and the error", async () => {
    vi.spyOn(api, "getPlotBoardProjection").mockRejectedValue(new Error("boom"));
    await refreshPlotBoard();
    expect(get(plotBoardError)).toBe("boom");
    clearPlotBoard();
    expect(get(plotBoardError)).toBeNull();
    expect(get(plotBoardStore)).toBeNull();
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

  it("realizeCard mints/attaches, refetches, and returns the minted scene id (S6b)", async () => {
    const realize = vi.spyOn(api, "realizeCard").mockResolvedValue({ ...card({ scene: "sc9" }), reanchored: ["c2"] });
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    const doc = { root: { id: "root", title: "Book" } } as unknown as StructureDocument;
    const structure = vi.spyOn(api, "getStructure").mockResolvedValue(doc);
    const realized = await realizeCard("c1", "chap1");
    expect(realize).toHaveBeenCalledWith("c1", "chap1");
    expect(refresh).toHaveBeenCalledTimes(1);
    // #2359: the minted scene joins the manuscript tree without a reload.
    expect(structure).toHaveBeenCalledTimes(1);
    expect(get(structureStore)).toBe(doc);
    // The undo command needs the scene id to delete the right scene, and the cards the
    // write re-anchored (ADR-0097 §6) to put their anchors back.
    expect(realized).toEqual({ sceneId: "sc9", reanchored: ["c2"] });
  });

  it("deleteCard deletes via the endpoint, then refetches the projection (#860)", async () => {
    const del = vi.spyOn(api, "deleteCard").mockResolvedValue({ entries: [] });
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await deleteCard("c1");
    expect(del).toHaveBeenCalledWith("c1");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("createCard creates a card, refetches, and returns the new id", async () => {
    const create = vi.spyOn(api, "createCard").mockResolvedValue(card());
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    const id = await createCard("New card");
    // `id` is undefined for a plain create (mint fresh); supplied only by redo (§7); a
    // deck's "New card" supplies the place (ADR-0097 §4).
    expect(create).toHaveBeenCalledWith("New card", undefined, undefined, undefined);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(id).toBe("c1");
  });

  it("createCard in a deck sends the place", async () => {
    const create = vi.spyOn(api, "createCard").mockResolvedValue(card());
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await createCard("New card", undefined, { deck: "d1" });
    expect(create).toHaveBeenCalledWith("New card", undefined, undefined, { deck: "d1" });
  });

  it("createCard forces a fresh fetch, not coalescing with a pre-create read-refresh", async () => {
    vi.spyOn(api, "createCard").mockResolvedValue(card());
    const stale = projection(); // the read-refresh's result: started BEFORE the create, 0 cards
    const withCard: PlotBoardProjection = {
      ...projection(),
      cards: [
        { id: "c1", title: "New card", synopsis: "", plotline: null, scene: null, container: null, deck: null, planned_in: null, planned_after: null, container_order: null, page_status: null, beats: [], sequence: null, causal_links: [], story_order: 0, story_movable: true },
      ],
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

  it("seedCardsFromManuscript seeds, refetches, and returns only the newly created ids", async () => {
    // The board already holds c1; the seed endpoint returns c1 + the new c2, so the
    // created-id diff (against plotBoardStore) yields just c2 for the undo command (§7).
    // Only `.id` is read off each, so a minimal cast keeps the fixture honest + small.
    plotBoardStore.set({ ...projection(), cards: [{ id: "c1" } as PlotBoardProjection["cards"][number]] });
    const seed = vi.spyOn(api, "seedFromManuscript").mockResolvedValue({
      entries: [{ id: "c1" }, { id: "c2" }] as Awaited<ReturnType<typeof api.seedFromManuscript>>["entries"],
    });
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    const created = await seedCardsFromManuscript();
    expect(seed).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(created).toEqual(["c2"]);
  });

  it("renameCard edits the displayed title through the text endpoint, then refetches", async () => {
    const text = vi.spyOn(api, "setCardText").mockResolvedValue(card());
    const save = vi.spyOn(api, "saveCard");
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    vi.spyOn(api, "getStructure").mockResolvedValue({ root: { id: "root", title: "Book" } } as unknown as StructureDocument);
    await renameCard("c1", "Renamed");
    expect(text).toHaveBeenCalledWith("c1", { title: "Renamed" });
    expect(save).not.toHaveBeenCalled(); // a written card's title is not a card save
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("saveCardSynopsis edits the displayed synopsis through the text endpoint", async () => {
    const text = vi.spyOn(api, "setCardText").mockResolvedValue(card());
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    vi.spyOn(api, "getStructure").mockResolvedValue({ root: { id: "root", title: "Book" } } as unknown as StructureDocument);
    await saveCardSynopsis("c1", "a fresh synopsis");
    expect(text).toHaveBeenCalledWith("c1", { synopsis: "a fresh synopsis" });
  });

  // ── Attach / detach and the text choice (ADR-0097 §3/§4) ──────────────────

  describe("attach / detach text choice", () => {
    const differ = () =>
      new HttpError("differ", 409, {
        message: "differ",
        code: "text_choice_required",
        scene_summary: "Scene says",
        card_synopsis: "Card says",
      });

    beforeEach(() => {
      vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
      vi.spyOn(api, "getStructure").mockResolvedValue({ root: { id: "root", title: "Book" } } as unknown as StructureDocument);
    });
    afterEach(() => confirmService.dismiss());

    it("detach needing no choice asks nothing and reports null", async () => {
      const detach = vi.spyOn(api, "detachCard").mockResolvedValue(card());
      expect(await detachCardScene("c1")).toBeNull();
      expect(detach).toHaveBeenCalledWith("c1", undefined);
      expect(confirmService.active).toBeNull();
    });

    it("a supplied choice (undo / redo replay) is passed through and reported back", async () => {
      const detach = vi.spyOn(api, "detachCard").mockResolvedValue(card());
      expect(await detachCardScene("c1", "card")).toBe("card");
      expect(detach).toHaveBeenCalledWith("c1", "card");
    });

    it("on the 409 it asks with both texts, and the primary button keeps the card's synopsis", async () => {
      const detach = vi
        .spyOn(api, "detachCard")
        .mockRejectedValueOnce(differ())
        .mockResolvedValueOnce(card());
      const pending = detachCardScene("c1");
      await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
      const ask = confirmService.active!;
      expect(ask.title).toBe("Which synopsis should the card keep?");
      expect(ask.confirmLabel).toBe("Keep the card's synopsis");
      expect(ask.secondaryLabel).toBe("Take the scene's summary");
      expect(ask.details?.join(" ")).toContain("Scene says");
      expect(ask.details?.join(" ")).toContain("Card says");
      await confirmService.resolve();
      expect(await pending).toBe("card");
      expect(detach).toHaveBeenLastCalledWith("c1", "card");
    });

    it("the secondary button picks the other text", async () => {
      const detach = vi
        .spyOn(api, "detachCard")
        .mockRejectedValueOnce(differ())
        .mockResolvedValueOnce(card());
      const pending = detachCardScene("c1");
      await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
      await confirmService.resolveSecondary();
      expect(await pending).toBe("scene");
      expect(detach).toHaveBeenLastCalledWith("c1", "scene");
    });

    it("attach asks which summary the scene keeps; confirm → scene, secondary → card", async () => {
      const attach = vi
        .spyOn(api, "attachCard")
        .mockRejectedValueOnce(differ())
        .mockResolvedValueOnce(card());
      const pending = attachCardScene("c1", "sc1");
      await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
      const ask = confirmService.active!;
      expect(ask.title).toBe("Which summary should the scene keep?");
      expect(ask.confirmLabel).toBe("Keep the scene's summary");
      expect(ask.secondaryLabel).toBe("Use the card's synopsis");
      await confirmService.resolve();
      expect(await pending).toBe("scene");
      expect(attach).toHaveBeenLastCalledWith("c1", "sc1", "scene");
    });

    it("cancelling aborts: 'cancelled', no retry, no board refetch", async () => {
      const detach = vi.spyOn(api, "detachCard").mockRejectedValue(differ());
      const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
      const pending = detachCardScene("c1");
      await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
      confirmService.dismiss();
      expect(await pending).toBe("cancelled");
      expect(detach).toHaveBeenCalledTimes(1);
      expect(refresh).not.toHaveBeenCalled();
    });

    it("any other failure propagates", async () => {
      vi.spyOn(api, "attachCard").mockRejectedValue(new HttpError("held", 409, "Another card holds it."));
      await expect(attachCardScene("c1", "sc1")).rejects.toThrow("held");
    });
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

  it("linkCardBeat appends a dropped beat to the card's existing links, then refetches", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1", beat_links: [{ plotline: "i1", beat_id: "b1" }] }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardBeat("c1", "i1", "b2");
    expect(save.mock.calls[0][0].metadata).toEqual({
      plotline: "p1",
      beat_links: [{ plotline: "i1", beat_id: "b1" }, { plotline: "i1", beat_id: "b2" }],
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("linkCardBeat skips the save + refetch when the beat is already linked (no-op)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ beat_links: [{ plotline: "i1", beat_id: "b1" }] }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardBeat("c1", "i1", "b1");
    expect(save).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("linkCardBeat adopts the beat's plotline as the primary when the card has none (ADR-0053 §4)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({})); // no primary, no links
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardBeat("c1", "i1", "b1");
    // The drop both links the beat AND lights the card in that thread's colour.
    expect(save.mock.calls[0][0].metadata).toEqual({
      plotline: "i1",
      beat_links: [{ plotline: "i1", beat_id: "b1" }],
    });
  });

  it("linkCardBeat still links a change-beat but never adopts the arc as primary (ADR-0080 §4)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({})); // no primary, no links
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardBeat("c1", "arc1", "b1", "plot:character_arc");
    // The beat_link IS created — only the primary-adoption is skipped (the backend
    // 422s an arc as a card's `plotline`).
    expect(save.mock.calls[0][0].metadata).toEqual({
      beat_links: [{ plotline: "arc1", beat_id: "b1" }],
    });
  });

  it("linkCardBeat keeps an existing primary when a beat from another plotline drops (multi-plotline)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardBeat("c1", "i2", "b9"); // a different plotline's beat
    // Primary p1 untouched; the second plotline shows only as a badge.
    expect(save.mock.calls[0][0].metadata).toEqual({
      plotline: "p1",
      beat_links: [{ plotline: "i2", beat_id: "b9" }],
    });
  });

  it("unlinkCardBeat removes one link; emptying it drops the key (sparse)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ plotline: "p1", beat_links: [{ plotline: "i1", beat_id: "b1" }] }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await unlinkCardBeat("c1", "i1", "b1");
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" });
  });

  it("linkCardCausal appends a target (dedup), refuses a self-link", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ causal_links: [{ target: "c2" }] }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await linkCardCausal("c1", "c3");
    expect(save.mock.calls[0][0].metadata.causal_links).toEqual([{ target: "c2" }, { target: "c3" }]);
    await linkCardCausal("c1", "c1"); // self → no save
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("unlinkCardCausal removes a target; emptying it drops the key (sparse)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ causal_links: [{ target: "c2" }] }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await unlinkCardCausal("c1", "c2");
    expect(save.mock.calls[0][0].metadata).toEqual({});
  });

  it("setCardPageStatus off_page sets the value; unwritten drops it (the sparse default)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card({ page_status: "unwritten" }));
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await setCardPageStatus("c1", "off_page");
    expect(save.mock.calls[0][0].metadata).toEqual({ page_status: "off_page" });

    vi.spyOn(api, "getCard").mockResolvedValue(card({ page_status: "off_page" }));
    await setCardPageStatus("c1", "unwritten");
    expect(save.mock.calls[1][0].metadata).toEqual({});
  });

  // ── Undo substrate (ADR-0053 §7) ──────────────────────────────────────────

  it("cardStateOf deep-copies metadata so a later live mutation can't reach the snapshot", () => {
    const live = card({ beat_links: [{ plotline: "p1", beat_id: "b1" }] });
    const snap = cardStateOf(live);
    (live.metadata.beat_links as unknown[]).push({ plotline: "p1", beat_id: "b2" });
    expect(snap.metadata.beat_links).toEqual([{ plotline: "p1", beat_id: "b1" }]);
  });

  it("getCardState reads the card's whole authored state", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue({ ...card({ plotline: "p1" }), body: "A synopsis." });
    expect(await getCardState("c1")).toEqual({
      title: "The letter",
      body: "A synopsis.",
      metadata: { plotline: "p1" },
      story_rank: null,
    });
  });

  it("getCardState carries the card's story rank (ADR-0097 §5)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue({ ...card(), story_rank: 4 });
    expect((await getCardState("c1")).story_rank).toBe(4);
  });

  it("restoreCardState fetches fresh (for the live revision) then saves the captured state", async () => {
    // The live card advanced to revision cr9 since capture — the restore must ride
    // THAT, not the stale revision baked into the snapshot, or it would 409.
    const getCard = vi.spyOn(api, "getCard").mockResolvedValue({ ...card({ plotline: "p9" }), revision: "cr9" });
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await restoreCardState("c1", { title: "Old title", body: "Old synopsis.", metadata: { plotline: "p1" } });
    expect(getCard).toHaveBeenCalledWith("c1");
    expect(save.mock.calls[0][0].revision).toBe("cr9"); // fresh revision
    expect(save.mock.calls[0][0].title).toBe("Old title");
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" });
    expect(save.mock.calls[0][1]).toBe("Old synopsis."); // body
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("recreateCard creates under the supplied id, then restores content (create-then-PUT)", async () => {
    const create = vi.spyOn(api, "createCard").mockResolvedValue(card());
    vi.spyOn(api, "getCard").mockResolvedValue(card());
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await recreateCard("c1", { title: "Restored", body: "Back.", metadata: { plotline: "p1" }, story_rank: 7 });
    expect(create).toHaveBeenCalledWith("Restored", "c1", 7); // id + story rank → same identity and place
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" });
    expect(save.mock.calls[0][1]).toBe("Back.");
  });

  it("recreateCard of a WRITTEN card restores its own text unwritten, then re-attaches with 'scene'", async () => {
    vi.spyOn(api, "createCard").mockResolvedValue(card());
    vi.spyOn(api, "getCard").mockResolvedValue(card());
    const save = vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    const attach = vi.spyOn(api, "attachCard").mockResolvedValue(card({ scene: "sc1" }));
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await recreateCard("c1", { title: "T", body: "B", metadata: { plotline: "p1", scene: "sc1" } });
    expect(save.mock.calls[0][0].metadata).toEqual({ plotline: "p1" }); // no scene while text restores
    expect(attach).toHaveBeenCalledWith("c1", "sc1", "scene");
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(attach.mock.invocationCallOrder[0]);
  });

  it("heldSceneIds lists every scene a card on the board holds", () => {
    plotBoardStore.set({
      ...projection(),
      cards: [
        { id: "a", scene: "sc1" },
        { id: "b", scene: null },
        { id: "c", scene: "sc3" },
      ] as PlotBoardProjection["cards"],
    });
    expect(heldSceneIds()).toEqual(["sc1", "sc3"]);
  });
  it("restore/recreate/deleteCard with refresh:false skip the board refetch (batched undo, #909)", async () => {
    vi.spyOn(api, "getCard").mockResolvedValue(card());
    vi.spyOn(api, "saveCard").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "createCard").mockResolvedValue(card());
    vi.spyOn(api, "deleteCard").mockResolvedValue({ entries: [] });
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await restoreCardState("c1", { title: "X", body: "", metadata: {} }, false);
    await recreateCard("c1", { title: "X", body: "", metadata: {} }, false);
    await deleteCard("c1", false);
    expect(refresh).not.toHaveBeenCalled(); // the batch does one refresh itself, later
  });

  // ── Realize-undo substrate (S6b) ──────────────────────────────────────────

  it("sceneReferents lists the cards referencing a scene, read off the live board", () => {
    const boardCard = (id: string, scene: string | null): PlotBoardProjection["cards"][number] =>
      ({ id, scene }) as PlotBoardProjection["cards"][number];
    plotBoardStore.set({
      ...projection(),
      cards: [boardCard("c1", "sc1"), boardCard("c2", "sc1"), boardCard("c3", "other"), boardCard("c4", null)],
    });
    expect(sceneReferents("sc1")).toEqual(["c1", "c2"]);
    expect(sceneReferents("gone")).toEqual([]);
  });

  it("readScene passes through to api.getScene", async () => {
    const scene = { id: "sc1", title: "The letter", body: "prose" } as Scene;
    vi.spyOn(api, "getScene").mockResolvedValue(scene);
    expect(await readScene("sc1")).toBe(scene);
  });

  it("deleteScene deletes the scene, updates the structure store, and refetches the board", async () => {
    const doc = { root: { id: "root", title: "Book" } } as unknown as StructureDocument;
    const del = vi.spyOn(api, "deleteScene").mockResolvedValue(doc);
    const refresh = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await deleteScene("sc1");
    expect(del).toHaveBeenCalledWith("sc1");
    expect(get(structureStore)).toBe(doc); // scene left the manuscript tree
    expect(refresh).toHaveBeenCalledTimes(1); // card projects homeless
  });
});
