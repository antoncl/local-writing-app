// Deck store (ADR-0097 §2) — the roster, the board-native create / delete, and the undo
// substrate (state-of / restore / recreate, and putting a card back in a deck). Each op
// refreshes the roster and/or the board; these pin that shape and the wire bodies.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import {
  createDeckOnBoard,
  deckEntriesStore,
  deckStateOf,
  deleteDeck,
  getDeckState,
  recreateDeck,
  restoreCardDeck,
  restoreDeckState,
  saveDeckEntry,
} from "./decks";
import type { CardEntry, DeckEntry, PlotBoardProjection } from "@/lib/types";

const deck = (over: Partial<DeckEntry> = {}): DeckEntry => ({
  id: "d1",
  title: "Backstory",
  body: "Mara's past.",
  revision: "r1",
  entry_type: "plot:deck",
  metadata: { plot_deck: "d0" },
  computed_metadata: {},
  ...over,
});

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

beforeEach(() => {
  vi.spyOn(api, "listCards").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
  vi.spyOn(api, "listDecks").mockResolvedValue({ entries: [] });
});
afterEach(() => vi.restoreAllMocks());

describe("deck store", () => {
  it("createDeckOnBoard mints a deck (optionally inside another), refreshes roster + board, returns the id", async () => {
    const create = vi.spyOn(api, "createDeck").mockResolvedValue(deck());
    expect(await createDeckOnBoard()).toBe("d1");
    expect(create).toHaveBeenCalledWith("New deck", { parent: undefined });
    await createDeckOnBoard("Childhood", "d0");
    expect(create).toHaveBeenLastCalledWith("Childhood", { parent: "d0" });
    expect(api.listDecks).toHaveBeenCalled();
    expect(api.getPlotBoardProjection).toHaveBeenCalled();
  });

  it("deleteDeck sets the roster from the delete's own answer and refreshes the board", async () => {
    vi.spyOn(api, "deleteDeck").mockResolvedValue({
      entries: [{ id: "d2", title: "Other", body: "", entry_type: "plot:deck", metadata: {} }],
    });
    await deleteDeck("d1");
    expect(get(deckEntriesStore).map((d) => d.id)).toEqual(["d2"]);
    expect(api.getPlotBoardProjection).toHaveBeenCalledTimes(1);
    await deleteDeck("d2", false); // a batched undo does its own single refresh
    expect(api.getPlotBoardProjection).toHaveBeenCalledTimes(1);
  });

  it("saveDeckEntry saves the whole entry and refreshes roster + board", async () => {
    const save = vi.spyOn(api, "saveDeck").mockResolvedValue(deck({ title: "Renamed" }));
    const saved = await saveDeckEntry(deck({ title: "Renamed" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ title: "Renamed" }), "Mara's past.");
    expect(saved.title).toBe("Renamed");
    expect(api.listDecks).toHaveBeenCalled();
  });
});

describe("deck undo substrate", () => {
  it("deckStateOf deep-copies metadata (the parent reference rides in it)", () => {
    const live = deck();
    const snap = deckStateOf(live);
    live.metadata.plot_deck = "changed";
    expect(snap).toEqual({ title: "Backstory", body: "Mara's past.", metadata: { plot_deck: "d0" } });
  });

  it("restoreDeckState fetches fresh for the live revision, then writes the captured state", async () => {
    vi.spyOn(api, "getDeck").mockResolvedValue(deck({ revision: "live", title: "Now" }));
    const save = vi.spyOn(api, "saveDeck").mockResolvedValue(deck());
    await restoreDeckState("d1", { title: "Then", body: "Old.", metadata: { plot_deck: "d0" } });
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ revision: "live", title: "Then", metadata: { plot_deck: "d0" } }), "Old.");
    expect(api.listDecks).toHaveBeenCalled();
  });

  it("getDeckState reads the whole authored state", async () => {
    vi.spyOn(api, "getDeck").mockResolvedValue(deck());
    expect(await getDeckState("d1")).toEqual({ title: "Backstory", body: "Mara's past.", metadata: { plot_deck: "d0" } });
  });

  it("recreateDeck creates under the ORIGINAL id, then restores content (no refresh when batched)", async () => {
    const create = vi.spyOn(api, "createDeck").mockResolvedValue(deck());
    vi.spyOn(api, "getDeck").mockResolvedValue(deck());
    const save = vi.spyOn(api, "saveDeck").mockResolvedValue(deck());
    await recreateDeck("d1", { title: "Backstory", body: "Mara's past.", metadata: { plot_deck: "d0" } }, false);
    expect(create).toHaveBeenCalledWith("Backstory", { id: "d1" });
    expect(save).toHaveBeenCalledTimes(1);
    expect(api.getPlotBoardProjection).not.toHaveBeenCalled();
  });

  it("restoreCardDeck places an unwritten card into the deck: membership only", async () => {
    const place = vi.spyOn(api, "placeCard").mockResolvedValue({} as CardEntry);
    await restoreCardDeck("c1", "d1", false, false);
    expect(place).toHaveBeenCalledWith("c1", { to: { deck: "d1" } });
  });

  it("restoreCardDeck sets a WRITTEN card's home deck by a card save (place refuses it)", async () => {
    const place = vi.spyOn(api, "placeCard");
    vi.spyOn(api, "getCard").mockResolvedValue({
      id: "c2",
      title: "Written",
      body: "",
      revision: "cr",
      entry_type: "plot:card",
      metadata: { scene: "s1", plot_deck: "" },
      computed_metadata: {},
    });
    const save = vi.spyOn(api, "saveCard").mockResolvedValue({} as CardEntry);
    await restoreCardDeck("c2", "d1", true, false);
    expect(place).not.toHaveBeenCalled();
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ metadata: { scene: "s1", plot_deck: "d1" } }), "");
  });
});
