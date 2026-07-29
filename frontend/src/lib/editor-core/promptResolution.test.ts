import { describe, expect, it } from "vitest";
import {
  promptEntriesForSurface,
  type PromptResolutionContext,
} from "@/lib/editor-core/promptResolution";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

function prompt(id: string, entryType: string): PromptEntrySummary {
  return { id, title: id, body: "", entry_type: entryType, metadata: {}, inputs: [] };
}

// Both prompt sub-types emit to the "append_to_body" surface, so the surface
// filter keeps both; the hidden filter is the only thing that removes one.
const schema = {
  entry_types: {
    "prompt:a": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:b": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
  },
} as unknown as MetadataSchema;

function ctx(over: Partial<PromptResolutionContext> = {}): PromptResolutionContext {
  return {
    metadataSchema: schema,
    promptEntries: [prompt("p-a", "prompt:a"), prompt("p-b", "prompt:b")],
    loreEntries: [],
    availableScenes: [],
    ...over,
  };
}

describe("promptEntriesForSurface — hidden filter (ADR-0049 slice 3)", () => {
  it("returns every matching prompt when nothing is hidden", () => {
    expect(promptEntriesForSurface(ctx(), "append_to_body").map((e) => e.id)).toEqual([
      "p-a",
      "p-b",
    ]);
  });

  it("drops a hidden prompt from discovery", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set(["p-a"]) }),
      "append_to_body",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-b"]);
  });

  it("an empty hidden set changes nothing", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set() }),
      "append_to_body",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-a", "p-b"]);
  });
});
