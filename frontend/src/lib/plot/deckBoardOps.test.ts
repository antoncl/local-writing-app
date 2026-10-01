// The deck gestures the board wires to its menus (ADR-0097 §7, §8): where "New card" puts a
// card, and the delete confirm's wording for a realized deck.
import { afterEach, describe, expect, it, vi } from "vitest";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { deckBoardOps, newCardTarget } from "./deckBoardOps";
import type { PlotUndoRecorder } from "./plotCommands";
import type { PlotBoardProjection } from "@/lib/types";

const projection = (decks: PlotBoardProjection["decks"]): PlotBoardProjection => ({
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  arcs: [],
  containers: [],
  decks,
  cards: [],
  diagnostics: [],
});
const deck = (id: string, realized_container: string | null = null) => ({
  id,
  title: id,
  synopsis: "",
  parent: null,
  movable: true,
  realized_container,
});

afterEach(() => confirmService.dismiss());

describe("newCardTarget", () => {
  it("homes the card in the deck, or plans it in the container the deck is realized as", () => {
    const p = projection([deck("d1"), deck("d2", "ch")]);
    expect(newCardTarget(p, "d1")).toEqual({ deck: "d1" });
    expect(newCardTarget(p, "d2")).toEqual({ planned_in: "ch", planned_after: null });
    expect(newCardTarget(null, "d1")).toEqual({ deck: "d1" });
  });
});

describe("deckBoardOps", () => {
  it("surfaces a refused realize in the banner instead of throwing", async () => {
    const recorder = { realizeDeck: vi.fn().mockRejectedValue(new Error("No level here")) } as unknown as PlotUndoRecorder;
    const setError = vi.fn();
    await deckBoardOps(recorder, () => null, setError).realize("d1");
    expect(setError).toHaveBeenCalledWith("No level here");
  });

  it("confirms deleting a realized deck even when empty, and says the chapter stays", () => {
    const ops = deckBoardOps({} as PlotUndoRecorder, () => projection([deck("d2", "ch")]), vi.fn());
    ops.remove("d2");
    expect(confirmService.active?.message).toContain("The chapter stays in the manuscript");
  });
});
