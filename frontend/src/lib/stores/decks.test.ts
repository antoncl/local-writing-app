// Deck store (ADR-0097 §2) — the roster, the board-native create / delete, and the undo
// substrate (state-of / restore / recreate, and putting a card back in a deck). Each op
// refreshes the roster and/or the board; these pin that shape and the wire bodies.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { HttpError } from "@/lib/api/core";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { plotBoardStore } from "@/lib/stores/plotBoard";
import {
  attachDeckContainer,
  createDeckOnBoard,
  deckEntriesStore,
  deckStateOf,
  deleteDeck,
  detachDeckContainer,
  getDeckState,
  realizeDeck,
  recreateDeck,
  restoreCardDeck,
  restoreDeckState,
  saveDeckEntry,
  setDeckText,
} from "./decks";
import type { CardEntry, DeckEntry, PlotBoardProjection, StructureDocument } from "@/lib/types";

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

describe("realize as a container (ADR-0097 §7)", () => {
  const differ = () =>
    new HttpError("differ", 409, {
      message: "differ",
      code: "text_choice_required",
      scene_summary: "Chapter says",
      card_synopsis: "Deck says",
    });

  beforeEach(() => {
    vi.spyOn(api, "getStructure").mockResolvedValue({ root: { id: "root", title: "Book" } } as unknown as StructureDocument);
  });
  afterEach(() => confirmService.dismiss());

  it("realizeDeck posts, refetches roster + board + tree, and returns the container and its planned cards", async () => {
    vi.spyOn(api, "realizeDeck").mockResolvedValue({ deck: deck(), container_id: "ch1", planned: ["a", "b"] });
    expect(await realizeDeck("d1")).toEqual({ containerId: "ch1", planned: ["a", "b"] });
    expect(api.listDecks).toHaveBeenCalled();
    expect(api.getPlotBoardProjection).toHaveBeenCalled();
    expect(api.getStructure).toHaveBeenCalled();
  });

  it("setDeckText sends the displayed text and refetches the tree (a realized deck's title is the container's)", async () => {
    const put = vi.spyOn(api, "setDeckText").mockResolvedValue(deck());
    await setDeckText("d1", { title: "Mara's past" });
    expect(put).toHaveBeenCalledWith("d1", { title: "Mara's past" });
    expect(api.getStructure).toHaveBeenCalled();
  });

  it("detach needing no choice asks nothing and reports null; a supplied choice is replayed", async () => {
    const detach = vi.spyOn(api, "detachDeck").mockResolvedValue(deck());
    expect(await detachDeckContainer("d1")).toBeNull();
    expect(detach).toHaveBeenLastCalledWith("d1", undefined);
    expect(confirmService.active).toBeNull();
    expect(await detachDeckContainer("d1", "card")).toBe("card");
    expect(detach).toHaveBeenLastCalledWith("d1", "card");
  });

  it("detach on the 409 asks with the deck wording; confirm keeps the deck's synopsis, secondary takes the chapter's", async () => {
    const detach = vi.spyOn(api, "detachDeck").mockRejectedValueOnce(differ()).mockResolvedValueOnce(deck());
    const pending = detachDeckContainer("d1");
    await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
    const ask = confirmService.active!;
    expect(ask.title).toBe("Which synopsis should the deck keep?");
    expect(ask.confirmLabel).toBe("Keep the deck's synopsis");
    expect(ask.secondaryLabel).toBe("Take the chapter's summary");
    expect(ask.details?.join(" ")).toContain("Chapter says");
    expect(ask.details?.join(" ")).toContain("Deck says");
    await confirmService.resolve();
    expect(await pending).toBe("card");
    expect(detach).toHaveBeenLastCalledWith("d1", "card");

    detach.mockRejectedValueOnce(differ()).mockResolvedValueOnce(deck());
    const again = detachDeckContainer("d1");
    await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
    await confirmService.resolveSecondary();
    expect(await again).toBe("scene");
  });

  it("attach asks which summary the chapter keeps; confirm → scene, secondary → card", async () => {
    const attach = vi.spyOn(api, "attachDeck").mockRejectedValueOnce(differ()).mockResolvedValueOnce(deck());
    const pending = attachDeckContainer("d1", "ch1");
    await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
    const ask = confirmService.active!;
    expect(ask.title).toBe("Which summary should the chapter keep?");
    expect(ask.confirmLabel).toBe("Keep the chapter's summary");
    expect(ask.secondaryLabel).toBe("Use the deck's synopsis");
    await confirmService.resolve();
    expect(await pending).toBe("scene");
    expect(attach).toHaveBeenLastCalledWith("d1", "ch1", "scene");
  });

  it("names the container by its level when the board knows it", async () => {
    plotBoardStore.set({
      ...projection(),
      containers: [{ id: "act1", title: "Act I", parent: null, level: 1, level_name: "Act" }],
    });
    vi.spyOn(api, "attachDeck").mockRejectedValueOnce(differ()).mockResolvedValueOnce(deck());
    const pending = attachDeckContainer("d1", "act1");
    await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
    expect(confirmService.active!.title).toBe("Which summary should the act keep?");
    await confirmService.resolve();
    await pending;
    plotBoardStore.set(null);
  });

  it("cancelling aborts: 'cancelled', no retry", async () => {
    const detach = vi.spyOn(api, "detachDeck").mockRejectedValue(differ());
    const pending = detachDeckContainer("d1");
    await vi.waitFor(() => expect(confirmService.active).not.toBeNull());
    confirmService.dismiss();
    expect(await pending).toBe("cancelled");
    expect(detach).toHaveBeenCalledTimes(1);
  });
});
