import { describe, expect, it } from "vitest";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";
import type { PromptResolutionContext } from "@/lib/editor-core/promptResolution";
import { DISPOSITION_FIELD, dispositionFor, promptSummariesToGroupNodes } from "@/lib/views/promptNodes";

// Each prompt sub-type carries a `context_strategy.output` (ADR-0054 §1/§2); the
// disposition is read off it. A type with no output is a snippet (no invocation
// contract). Roleplay inherits continuation's append_to_body — the schema the
// frontend receives resolves that inheritance, so we model it here as if resolved.
const SCHEMA = {
  entry_types: {
    "prompt:continuation": { name: "Continuation", prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:revise:scene": { name: "Revise scene", prompt: { context_strategy: { output: { kind: "replace_selection" } } } },
    "prompt:general": { name: "General", prompt: { context_strategy: { output: { kind: "chat_panel" } } } },
    "prompt:revise:entry": {
      name: "Revise entry",
      prompt: { context_strategy: { output: { kind: "chat_panel", commit: { review: "visual_diff" } } } },
    },
    "prompt:snippet": { name: "Snippet", prompt: { context_strategy: {} } },
    "prompt:broken": { name: "Broken", prompt: { context_strategy: { output: { kind: "who_knows" } } } },
  },
  fields: {},
} as unknown as MetadataSchema;

function prompt(id: string, entry_type: string, title = id): PromptEntrySummary {
  return { id, title, body: "", entry_type, metadata: {}, inputs: [] };
}

const ctx: PromptResolutionContext = {
  metadataSchema: SCHEMA,
  promptEntries: [],
  loreEntries: [],
  availableScenes: [],
};

describe("dispositionFor — the five shelves (#951)", () => {
  it("maps each output disposition to its shelf", () => {
    expect(dispositionFor(ctx, prompt("a", "prompt:continuation")).label).toBe("Continue");
    expect(dispositionFor(ctx, prompt("b", "prompt:revise:scene")).label).toBe("Revise prose");
    expect(dispositionFor(ctx, prompt("c", "prompt:general")).label).toBe("Chat");
    expect(dispositionFor(ctx, prompt("d", "prompt:revise:entry")).label).toBe("Revise entities");
  });

  it("shelves a no-contract prompt (and any unknown kind) under Snippets", () => {
    // A snippet declares no output — the definition of 'no invocation contract'.
    expect(dispositionFor(ctx, prompt("e", "prompt:snippet")).label).toBe("Snippets");
    // A misconfigured concrete type can't be invoked either → Snippets, not a crash.
    expect(dispositionFor(ctx, prompt("f", "prompt:broken")).label).toBe("Snippets");
    // An entry_type absent from the schema resolves to no output → Snippets.
    expect(dispositionFor(ctx, prompt("g", "prompt:ghost")).label).toBe("Snippets");
  });

  it("has commit distinguish Revise entities from a plain Chat on the same chat_panel", () => {
    expect(dispositionFor(ctx, prompt("c", "prompt:general")).label).toBe("Chat");
    expect(dispositionFor(ctx, prompt("d", "prompt:revise:entry")).label).toBe("Revise entities");
  });
});

describe("promptSummariesToGroupNodes — the pane lift", () => {
  it("stamps the disposition label into metadata for group_by to bucket on", () => {
    const [node] = promptSummariesToGroupNodes([prompt("a", "prompt:continuation")], SCHEMA);
    expect(node.metadata[DISPOSITION_FIELD]).toBe("Continue");
    // The summary's own fields survive the lift.
    expect(node.id).toBe("a");
    expect(node.entry_type).toBe("prompt:continuation");
  });

  it("clusters the roster into shelf order (first-seen == rank), preserving intra-shelf order", () => {
    // Deliberately interleaved input across shelves; snippet last regardless.
    const roster = [
      prompt("snip", "prompt:snippet"),
      prompt("gen", "prompt:general"),
      prompt("cont-b", "prompt:continuation", "Beta"),
      prompt("brainstorm", "prompt:revise:entry"),
      prompt("cont-a", "prompt:continuation", "Alpha"),
      prompt("revise", "prompt:revise:scene"),
    ];
    const order = promptSummariesToGroupNodes(roster, SCHEMA).map((n) => n.metadata[DISPOSITION_FIELD]);
    // Shelves appear in rank order…
    expect(order).toEqual(["Continue", "Continue", "Revise prose", "Chat", "Revise entities", "Snippets"]);
    // …and within the Continue shelf the two keep their input order (stable sort):
    const continueIds = promptSummariesToGroupNodes(roster, SCHEMA)
      .filter((n) => n.metadata[DISPOSITION_FIELD] === "Continue")
      .map((n) => n.id);
    expect(continueIds).toEqual(["cont-b", "cont-a"]);
  });

  it("does not mutate the caller's entries", () => {
    const original = prompt("a", "prompt:continuation");
    promptSummariesToGroupNodes([original], SCHEMA);
    expect(original.metadata).toEqual({});
  });
});
