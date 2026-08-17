import { describe, expect, it } from "vitest";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";
import type { PromptResolutionContext } from "@/lib/editor-core/promptResolution";
import {
  CHAT_DISPOSITION_LABEL,
  DISPOSITION_FIELD,
  DISPOSITION_LABELS,
  dispositionFieldDef,
  dispositionFor,
  promptSummariesToGroupNodes,
  REVISE_ENTITIES_DISPOSITION_LABEL,
} from "@/lib/views/promptNodes";

// Each prompt sub-type carries a `context_strategy.output` (ADR-0054 §1/§2); the
// disposition is read off it. A type with no output is a snippet (no invocation
// contract). Roleplay inherits continuation's append_to_body — the schema the
// frontend receives resolves that inheritance, so we model it here as if resolved.
const SCHEMA = {
  entry_types: {
    "prompt:continuation": { name: "Continuation", prompt: { context_strategy: { output: { handler: "inline" } } } },
    "prompt:revise:scene": { name: "Revise scene", prompt: { context_strategy: { output: { handler: "inline", destination: "selection" } } } },
    "prompt:general": { name: "General", prompt: { context_strategy: {} } },
    "prompt:revise:entry": {
      name: "Revise entry",
      prompt: { context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } } },
    },
    // A snippet carries NO context_strategy — that absence (vs general's empty one) is
    // what makes it non-invocable (ADR-0065).
    "prompt:snippet": { name: "Snippet" },
    "prompt:broken": { name: "Broken", prompt: { context_strategy: { output: { handler: "who_knows" } } } },
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

  it("shelves a no-contract prompt (and any unregistered handler) under Snippets", () => {
    // A snippet declares no output — the definition of 'no invocation contract'.
    expect(dispositionFor(ctx, prompt("e", "prompt:snippet")).label).toBe("Snippets");
    // A misconfigured concrete type (a non-empty but unregistered handler) can't be
    // invoked either → Snippets, not a crash.
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

describe("dispositionFieldDef — the designer computed field (#960)", () => {
  it("is a computed select whose choices are the five shelf labels", () => {
    const def = dispositionFieldDef();
    expect(def.type).toBe("select");
    expect(def.category).toBe("computed");
    expect(def.options.map((o) => o.value)).toEqual([
      "Continue",
      "Revise prose",
      "Chat",
      "Revise entities",
      "Snippets",
    ]);
    // The value set is exactly the labels the lift stamps, so a filter/group on
    // this field matches the buckets `promptSummariesToGroupNodes` produces.
    expect(def.options.map((o) => o.value)).toEqual(DISPOSITION_LABELS);
  });

  it("exports the two chat-reachable labels bound to the same disposition strings", () => {
    // chatNodes' seed-disposition descriptor and the Openable predicate reuse these,
    // so a rename of the shelf labels can't drift them out of sync.
    expect(CHAT_DISPOSITION_LABEL).toBe(dispositionFor(ctx, prompt("c", "prompt:general")).label);
    expect(REVISE_ENTITIES_DISPOSITION_LABEL).toBe(
      dispositionFor(ctx, prompt("d", "prompt:revise:entry")).label,
    );
  });
});
