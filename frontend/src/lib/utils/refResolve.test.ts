// Pure unit tests for the shared id → node resolver (#2010 lift of
// ReferencePicker's resolveRefById). No Svelte mount needed.
import { describe, expect, it } from "vitest";
import { buildRefResolver } from "./refResolve";
import type { StructureDocument, TagEntry } from "@/lib/types";

const structure: StructureDocument = {
  root: {
    id: "node_root",
    type: "manuscript:root",
    title: "Root",
    children: [
      { id: "node_1", type: "manuscript:scene", title: "Chapter One", scene_id: "scene_1", children: [] },
    ],
  },
} as unknown as StructureDocument;

describe("buildRefResolver", () => {
  it("resolves a scene id off the structure tree", () => {
    const resolve = buildRefResolver({ structure });
    expect(resolve("scene_1")).toEqual({ id: "scene_1", kind: "manuscript", title: "Chapter One", entry_type: "manuscript:scene" });
  });

  it("resolves a lore id", () => {
    const resolve = buildRefResolver({
      loreEntries: [{ id: "lore_1", title: "Elien", body: "", entry_type: "lore:character", metadata: {} }],
    });
    expect(resolve("lore_1")).toEqual({ id: "lore_1", kind: "lore", title: "Elien", entry_type: "lore:character" });
  });

  it("resolves a prompt (snippet) id", () => {
    const resolve = buildRefResolver({
      promptEntries: [{ id: "prompt_1", title: "Continue", entry_type: "prompt:base" } as never],
    });
    expect(resolve("prompt_1")).toEqual({ id: "prompt_1", kind: "snippet", title: "Continue", entry_type: "prompt:base" });
  });

  it("resolves a tag id via the full tag roster (entry_type included)", () => {
    const tag: TagEntry = { id: "tag_1", title: "Grief", entry_type: "tag:theme", metadata: {} };
    const resolve = buildRefResolver({ tagById: new Map([[tag.id, tag]]) });
    expect(resolve("tag_1")).toEqual({ id: "tag_1", kind: "tag", title: "Grief", entry_type: "tag:theme" });
  });

  it("falls back to a title-only tag resolve when only tagTitleById is given", () => {
    const resolve = buildRefResolver({ tagTitleById: new Map([["tag_2", "Hope"]]) });
    expect(resolve("tag_2")).toEqual({ id: "tag_2", kind: "tag", title: "Hope" });
  });

  it("returns null for an id none of the sources resolve", () => {
    const resolve = buildRefResolver({});
    expect(resolve("nope")).toBeNull();
  });
});
