import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Mock the HTTP client so refreshTagNodes is tested against a controlled
// response, not the network (ADR-0082 slice 1).
const { listTagEntries } = vi.hoisted(() => ({ listTagEntries: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { listTagEntries } }));

import type { TagEntry } from "@/lib/types";
import { clearTagNodes, refreshTagNodes, tagById, tagNodesStore, tagTitleById } from "./tagNodes";

const T = (id: string, title: string): TagEntry => ({
  id,
  title,
  entry_type: "tag:tag",
  metadata: {},
});

describe("tagNodes store (ADR-0082 slice 1)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    clearTagNodes();
  });

  it("refreshTagNodes populates the store from the API", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal"), T("tag_2", "Urban")] });
    await refreshTagNodes();
    expect(get(tagNodesStore).map((t) => t.id)).toEqual(["tag_1", "tag_2"]);
  });

  it("tagById maps ids to the whole entry", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    expect(get(tagById).get("tag_1")).toEqual(T("tag_1", "Coastal"));
    expect(get(tagById).get("tag_missing")).toBeUndefined();
  });

  it("tagTitleById maps ids to titles", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal"), T("tag_2", "Urban")] });
    await refreshTagNodes();
    const map = get(tagTitleById);
    expect(map.get("tag_1")).toBe("Coastal");
    expect(map.get("tag_2")).toBe("Urban");
    expect(map.get("tag_missing")).toBeUndefined();
  });

  it("clearTagNodes empties both the roster and the derived title map", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    clearTagNodes();
    expect(get(tagNodesStore)).toEqual([]);
    expect(get(tagTitleById).size).toBe(0);
  });

  it("refreshTagNodes swallows a fetch error and keeps the previous roster", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    listTagEntries.mockRejectedValueOnce(new Error("offline"));
    await expect(refreshTagNodes()).resolves.toBeUndefined();
    expect(get(tagNodesStore).map((t) => t.id)).toEqual(["tag_1"]);
  });

  it("a late response never overwrites a newer one (sequence guard)", async () => {
    let resolveFirst!: (value: { tags: TagEntry[] }) => void;
    let resolveSecond!: (value: { tags: TagEntry[] }) => void;
    listTagEntries
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveFirst = resolve; }),
      )
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveSecond = resolve; }),
      );

    const first = refreshTagNodes();
    const second = refreshTagNodes();

    // The SECOND call resolves first — the first call's response arrives late.
    resolveSecond({ tags: [T("tag_2", "Second")] });
    await second;
    resolveFirst({ tags: [T("tag_1", "First")] });
    await first;

    expect(get(tagNodesStore).map((t) => t.id)).toEqual(["tag_2"]);
  });
});
