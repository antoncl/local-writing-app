import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Mock the HTTP client so refreshTagNodes is tested against a controlled
// response, not the network (ADR-0082 slice 1).
const { listTagEntries } = vi.hoisted(() => ({ listTagEntries: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { listTagEntries } }));

import type { TagEntry } from "@/lib/types";
import { clearTagNodes, refreshTagNodes, tagNodesStore, tagTitleById } from "./tagNodes";

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
});
