import { describe, expect, it } from "vitest";
import {
  hidePromptEntries,
  promptEntriesForSurface,
  promptTargetsEntryType,
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

// The per-node brainstorm filter (ADR-0048 S8b): the ＋New menu shows only the
// entry_patch prompts whose entry-input target admits the open node's type, so a
// lore entry offers the lore revise prompt and a plot card the plot-card one.
describe("promptTargetsEntryType (ADR-0048 S8b)", () => {
  const isaSchema = {
    entry_types: {
      "lore:base": {},
      "lore:character": { parent: "lore:base" },
      "plot:base": {},
      "plot:card": { parent: "plot:base" },
    },
  } as unknown as MetadataSchema;

  function isaCtx(): PromptResolutionContext {
    return { metadataSchema: isaSchema, promptEntries: [], loreEntries: [], availableScenes: [] };
  }

  function targeted(id: string, targetType: string): PromptEntrySummary {
    return {
      id,
      title: id,
      body: "",
      entry_type: "prompt:revise",
      metadata: {},
      inputs: [
        { name: "entry", type: "context_pick", label: "E", target: { sources: [{ expr: { type: targetType } }] } },
      ],
    } as unknown as PromptEntrySummary;
  }

  const lorePrompt = targeted("p-lore", "lore:base");
  const cardPrompt = targeted("p-card", "plot:card");

  it("admits a subject that is-a the prompt's target type", () => {
    expect(promptTargetsEntryType(isaCtx(), lorePrompt, "lore:character")).toBe(true); // descendant
    expect(promptTargetsEntryType(isaCtx(), cardPrompt, "plot:card")).toBe(true); // exact
  });

  it("rejects a cross-kind subject", () => {
    expect(promptTargetsEntryType(isaCtx(), lorePrompt, "plot:card")).toBe(false);
    expect(promptTargetsEntryType(isaCtx(), cardPrompt, "lore:character")).toBe(false);
  });

  it("an untargeted prompt applies to any resolved subject", () => {
    const untargeted = prompt("p-any", "prompt:revise"); // inputs: []
    expect(promptTargetsEntryType(isaCtx(), untargeted, "plot:card")).toBe(true);
  });

  it("shows nothing until the subject type resolves", () => {
    expect(promptTargetsEntryType(isaCtx(), lorePrompt, "")).toBe(false);
    expect(promptTargetsEntryType(isaCtx(), lorePrompt, null)).toBe(false);
  });
});
