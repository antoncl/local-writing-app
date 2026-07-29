import { describe, expect, it } from "vitest";
import {
  hidePromptEntries,
  promptEntriesForSurface,
  type PromptResolutionContext,
} from "@/lib/editor-core/promptResolution";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

function prompt(id: string, entryType: string): PromptEntrySummary {
  return { id, title: id, body: "", entry_type: entryType, metadata: {}, inputs: [] };
}

// prompt:a / prompt:b emit to append_to_body; prompt:chat routes to the chat
// panel, so the surface filter partitions them and the hidden filter removes one.
const schema = {
  entry_types: {
    "prompt:a": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:b": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:chat": { prompt: { context_strategy: { output: { kind: "chat_panel" } } } },
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

  // The chat "Pick a prompt" list (ChatBodyView) routes through this seam (#682),
  // so a hidden chat_panel prompt must drop out of the chat surface too.
  it("drops a hidden prompt from the chat_panel surface", () => {
    const base = ctx({ promptEntries: [prompt("p-chat", "prompt:chat")] });
    expect(promptEntriesForSurface(base, "chat_panel").map((e) => e.id)).toEqual(["p-chat"]);
    const hidden = ctx({
      promptEntries: [prompt("p-chat", "prompt:chat")],
      hiddenPromptIds: new Set(["p-chat"]),
    });
    expect(promptEntriesForSurface(hidden, "chat_panel")).toEqual([]);
  });
});

// The shared seam every prompt-discovery surface routes through (#682) —
// promptEntriesForSurface above, plus NodePicker's snippet picker directly.
describe("hidePromptEntries (ADR-0049 #682)", () => {
  const entries = [prompt("keep", "prompt:a"), prompt("gone", "prompt:a")];

  it("removes the hidden ids", () => {
    expect(hidePromptEntries(entries, new Set(["gone"])).map((e) => e.id)).toEqual(["keep"]);
  });

  it("returns the roster unchanged for an undefined or empty set", () => {
    expect(hidePromptEntries(entries, undefined)).toBe(entries);
    expect(hidePromptEntries(entries, new Set())).toBe(entries);
  });
});
