import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { cardEntriesStore, refreshCards, setCards, clearCards } from "./plotCards";

const card = (id: string, title: string) =>
  ({ id, title, body: "", entry_type: "plot:card", metadata: {} }) as never;

afterEach(() => {
  clearCards();
  vi.restoreAllMocks();
});

describe("plotCards store", () => {
  it("refreshCards loads the flat card list from the API", async () => {
    vi.spyOn(api, "listCards").mockResolvedValue({ entries: [card("c1", "Break-in"), card("c2", "Getaway")] });
    await refreshCards();
    expect(get(cardEntriesStore).map((c) => c.id)).toEqual(["c1", "c2"]);
  });

  it("setCards sets the roster directly (no round-trip)", () => {
    setCards([card("c3", "Alibi")]);
    expect(get(cardEntriesStore).map((c) => c.id)).toEqual(["c3"]);
  });

  it("clearCards empties the roster", () => {
    setCards([card("c1", "Break-in")]);
    clearCards();
    expect(get(cardEntriesStore)).toEqual([]);
  });
});
