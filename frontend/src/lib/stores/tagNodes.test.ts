import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Mock the HTTP client so refreshTagNodes is tested against a controlled
// response, not the network (ADR-0082 slice 1). `createTagEntry` backs
// `resolveAdoptedTagFieldValue` (#1797 — accept-time mint).
const { listTagEntries, createTagEntry } = vi.hoisted(() => ({
  listTagEntries: vi.fn(),
  createTagEntry: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: { listTagEntries, createTagEntry } }));

import type { MetadataSchema, TagEntry } from "@/lib/types";
import {
  canonicalTagId,
  clearTagNodes,
  findTagByTitle,
  liveTags,
  refreshTagNodes,
  resolveAdoptedTagFields,
  resolveAdoptedTagFieldValue,
  resolveOrCreateTag,
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

describe("resolveOrCreateTag (ADR-0082 §2, round 2 Y3 — the ONE resolve-or-mint sequence)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    createTagEntry.mockReset();
    clearTagNodes();
  });

  it("an existing title (case-insensitive) wins over minting a duplicate", async () => {
    // The invariant ReferencePicker's own "stale-roster" race test used to
    // pin via a same-module function spy (no longer possible now that this
    // sequence lives in ONE shared function, round 2 Y3) — tested directly
    // here instead, at the layer that now owns it.
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_existing", "Mystery")] });
    await refreshTagNodes();
    const tag = await resolveOrCreateTag("mystery", "tag:tag", null);
    expect(tag.id).toBe("tag_existing");
    expect(createTagEntry).not.toHaveBeenCalled();
  });

  it("mints and lands the response in the roster when nothing matches", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    createTagEntry.mockResolvedValueOnce(T("tag_new", "Seafaring"));
    const tag = await resolveOrCreateTag("Seafaring", "tag:tag", "layer_1");
    expect(tag.id).toBe("tag_new");
    expect(createTagEntry).toHaveBeenCalledWith("Seafaring", "tag:tag", null, "layer_1");
    expect(get(tagById).get("tag_new")?.title).toBe("Seafaring");
  });

  it("propagates a createTagEntry rejection — nothing is silently swallowed", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    createTagEntry.mockRejectedValueOnce(new Error("offline"));
    await expect(resolveOrCreateTag("Seafaring", "tag:tag", null)).rejects.toThrow("offline");
  });
});

describe("resolveAdoptedTagFieldValue (ADR-0082 §2 / #1797 / #1799 — accept-time mint)", () => {
  beforeEach(() => {
    listTagEntries.mockReset();
    createTagEntry.mockReset();
    clearTagNodes();
  });

  it("passes an already-known id through unchanged", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    const resolved = await resolveAdoptedTagFieldValue(["tag_1"], "tag:tag", null);
    expect(resolved).toEqual(["tag_1"]);
    expect(createTagEntry).not.toHaveBeenCalled();
  });

  it("resolves a bare title matching an existing tag — never creates a duplicate", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Politics")] });
    await refreshTagNodes();
    const resolved = await resolveAdoptedTagFieldValue(["politics"], "tag:tag", null);
    expect(resolved).toEqual(["tag_1"]);
    expect(createTagEntry).not.toHaveBeenCalled();
  });

  it("mints exactly once for an unmatched title, at the given layer, and lands it in the roster", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    createTagEntry.mockResolvedValueOnce(T("tag_new", "Seafaring"));
    const resolved = await resolveAdoptedTagFieldValue(["Seafaring"], "tag:tag", "layer_1");
    expect(resolved).toEqual(["tag_new"]);
    expect(createTagEntry).toHaveBeenCalledTimes(1);
    expect(createTagEntry).toHaveBeenCalledWith("Seafaring", "tag:tag", null, "layer_1");
    // The POST's own response lands in the roster immediately (P3 parity).
    expect(get(tagById).get("tag_new")?.title).toBe("Seafaring");
  });

  it("a repeated unmatched title within one field mints once, not twice", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    createTagEntry.mockResolvedValueOnce(T("tag_new", "Seafaring"));
    const resolved = await resolveAdoptedTagFieldValue(["Seafaring", "seafaring"], "tag:tag", null);
    expect(resolved).toEqual(["tag_new", "tag_new"]);
    expect(createTagEntry).toHaveBeenCalledTimes(1);
  });

  it("drops non-string and blank items, and a non-array value resolves to []", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    const resolved = await resolveAdoptedTagFieldValue(["  ", 5, null], "tag:tag", null);
    expect(resolved).toEqual([]);
    expect(createTagEntry).not.toHaveBeenCalled();
    expect(await resolveAdoptedTagFieldValue("not-an-array", "tag:tag", null)).toEqual([]);
  });

  it("round 2 (Y1): a rejection stops the loop — item before it stays minted, item after it is never attempted", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [] });
    await refreshTagNodes();
    createTagEntry
      .mockResolvedValueOnce(T("tag_a", "A")) // item 1: succeeds and mints
      .mockRejectedValueOnce(new Error("network down")); // item 2: rejects
    await expect(resolveAdoptedTagFieldValue(["A", "B", "C"], "tag:tag", null)).rejects.toThrow(
      "network down",
    );
    // Sequential + await-per-item means item 3 ("C") is never even attempted.
    expect(createTagEntry).toHaveBeenCalledTimes(2);
    // "A" already landed — a real, roster-visible node; nothing here rolls it
    // back (there is nothing TO roll back).
    expect(get(tagById).get("tag_a")?.title).toBe("A");
  });
});

describe("resolveAdoptedTagFields (#1821 — the shared field-loop both accept paths call)", () => {
  // Same fixture shape as treeActions.createDraft.test.ts's SCHEMA_WITH_TAGS,
  // plus a non-tag entity_ref field (a plain lore-entry picker) and a text
  // field, to pin that only the tag-shaped field gets rewritten.
  const SCHEMA = {
    entry_types: { "lore:character": { name: "Character" }, "tag:tag": { name: "Tag", kind: "tag" } },
    fields: {
      tags: {
        name: "Tags",
        type: "entity_ref_list",
        options: [],
        picker_config: { create_missing: true, sources: [{ kind: "tag", expr: { type: "tag:tag" } }] },
      },
      companion: {
        name: "Companion",
        type: "entity_ref",
        options: [],
        picker_config: { create_missing: true, sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
      },
      bio: { name: "Bio", type: "text", options: [] },
    },
  } as unknown as MetadataSchema;

  beforeEach(() => {
    listTagEntries.mockReset();
    createTagEntry.mockReset();
    clearTagNodes();
  });

  it("resolves only the tag field, leaving a non-tag ref and a plain field untouched", async () => {
    listTagEntries.mockResolvedValueOnce({ tags: [T("tag_1", "Coastal")] });
    await refreshTagNodes();
    createTagEntry.mockResolvedValueOnce(T("tag_new", "Seafaring"));

    const fields = {
      tags: ["coastal", "Seafaring"],
      companion: "lore_someone",
      bio: "unrelated text",
    };
    await resolveAdoptedTagFields(fields, SCHEMA, null);

    expect(fields.tags).toEqual(["tag_1", "tag_new"]);
    expect(fields.companion).toBe("lore_someone");
    expect(fields.bio).toBe("unrelated text");
    expect(createTagEntry).toHaveBeenCalledTimes(1);
    expect(createTagEntry).toHaveBeenCalledWith("Seafaring", "tag:tag", null, null);
  });
});
