// ADR-0099 §4: `createTodos` throws only when the TODOs were NOT written — a
// failure after the write would make the review's Done retry create them again.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { todoActions } from "./todoActions.svelte";
import type { NewTodo } from "@/lib/types";

const ITEM: NewTodo = {
  scope: "node",
  node_id: "lore-2",
  text: "Its docks run on the outer rim.",
  source: { node_id: "lore-1", reason: "follow_up" },
};

afterEach(() => vi.restoreAllMocks());

describe("todoActions.createTodos", () => {
  it("a failed list refresh after the write does not throw (no duplicate TODOs on retry)", async () => {
    const create = vi.spyOn(api, "createTodos").mockResolvedValue({ items: [] } as never);
    vi.spyOn(api, "getTodos").mockRejectedValue(new Error("refresh timed out"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(todoActions.createTodos([ITEM])).resolves.toBeUndefined();
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("a failed write does throw, so the review stays open", async () => {
    vi.spyOn(api, "createTodos").mockRejectedValue(new Error("write failed"));
    const refresh = vi.spyOn(api, "getTodos");
    await expect(todoActions.createTodos([ITEM])).rejects.toThrow("write failed");
    expect(refresh).not.toHaveBeenCalled();
  });
});
