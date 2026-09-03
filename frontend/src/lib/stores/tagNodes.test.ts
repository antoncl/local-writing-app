import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Mock the HTTP client so refreshTagNodes is tested against a controlled
// response, not the network (ADR-0082 slice 1).
const { listTagEntries } = vi.hoisted(() => ({ listTagEntries: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { listTagEntries } }));

import type { TagEntry } from "@/lib/types";
import {
  canonicalTagId,
  clearTagNodes,
  findTagByTitle,
  liveTags,
  refreshTagNodes,
  tagById,
  tagNodesStore,
  tagTitleById,
} from "./tagNodes";

const T = (id: string, title: string, entryType = "tag:tag", mergedInto: string | null = null): TagEntry => ({
  id,
  title,
  entry_type: entryType,
  metadata: {},
  merged_into: mergedInto,
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

describe("canonicalTagId (ADR-0082 §5 / F1)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    clearTagNodes();
  });

  it("is identity for an unmerged id, and for an id outside the roster", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    expect(canonicalTagId("tag_1")).toBe("tag_1");
    expect(canonicalTagId("tag_ghost")).toBe("tag_ghost");
  });

  it("follows a single-hop redirect to the survivor", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_mirror", "mirror", "tag:tag", "tag_mirrors"), T("tag_mirrors", "mirrors")],
    });
    await refreshTagNodes();
    expect(canonicalTagId("tag_mirror")).toBe("tag_mirrors");
  });

  it("follows a chain to its end", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [
        T("tag_a", "a", "tag:tag", "tag_b"),
        T("tag_b", "b", "tag:tag", "tag_c"),
        T("tag_c", "c"),
      ],
    });
    await refreshTagNodes();
    expect(canonicalTagId("tag_a")).toBe("tag_c");
  });

  it("stops at the first repeat rather than looping forever on a cycle", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_a", "a", "tag:tag", "tag_b"), T("tag_b", "b", "tag:tag", "tag_a")],
    });
    await refreshTagNodes();
    expect(["tag_a", "tag_b"]).toContain(canonicalTagId("tag_a"));
  });

  it("tagTitleById maps a merged id to the SURVIVOR's title", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_mirror", "mirror", "tag:tag", "tag_mirrors"), T("tag_mirrors", "mirrors")],
    });
    await refreshTagNodes();
    const map = get(tagTitleById);
    expect(map.get("tag_mirror")).toBe("mirrors");
    expect(map.get("tag_mirrors")).toBe("mirrors");
  });
});

describe("liveTags (ADR-0082 §5)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    clearTagNodes();
  });

  it("excludes a merged tag and keeps an unmerged one", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_mirror", "mirror", "tag:tag", "tag_mirrors"), T("tag_mirrors", "mirrors")],
    });
    await refreshTagNodes();
    expect(get(liveTags).map((t) => t.id)).toEqual(["tag_mirrors"]);
  });
});

describe("findTagByTitle (ADR-0082 §2 / F3)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    clearTagNodes();
  });

  it("matches case-insensitively and trims the query", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    expect(findTagByTitle("coastal")?.id).toBe("tag_1");
    expect(findTagByTitle("  COASTAL  ")?.id).toBe("tag_1");
  });

  it("returns undefined when nothing matches, including an empty query", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    expect(findTagByTitle("urban")).toBeUndefined();
    expect(findTagByTitle("")).toBeUndefined();
    expect(findTagByTitle("   ")).toBeUndefined();
  });

  it("an entryType filter narrows to one vocabulary", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_1", "Editor", "tag:tag"), T("tag_2", "Editor", "tag:assistant_tag")],
    });
    await refreshTagNodes();
    expect(findTagByTitle("Editor", "tag:assistant_tag")?.id).toBe("tag_2");
    expect(findTagByTitle("Editor", "tag:tag")?.id).toBe("tag_1");
    expect(findTagByTitle("Editor")?.id).toBe("tag_1"); // omitted → first match
  });

  it("skips a merged tag by its old title (ADR-0082 §5)", async () => {
    listTagEntries.mockResolvedValueOnce({
      tags: [T("tag_mirror", "mirror", "tag:tag", "tag_mirrors"), T("tag_mirrors", "mirrors")],
    });
    await refreshTagNodes();
    expect(findTagByTitle("mirror")).toBeUndefined();
    expect(findTagByTitle("mirrors")?.id).toBe("tag_mirrors");
  });
});
