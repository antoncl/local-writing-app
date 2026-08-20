import { describe, expect, it } from "vitest";
import type { MetadataSchema, PromptContextStrategy, PromptEntrySummary } from "@/lib/types";
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

// ADR-0065 S3: each prompt INSTANCE carries its own `context_strategy.output`; the
// disposition is read off it, never a schema-type lookup. Invocability is the
// entry_type — only `prompt:snippet` is uninvocable, whatever its (usually absent)
// config; every other entry_type defaults to a plain conversation with no strategy.
const SCHEMA = { entry_types: {}, fields: {} } as unknown as MetadataSchema;

function prompt(
  id: string,
  entry_type: string,
  title = id,
  contextStrategy?: PromptContextStrategy | null,
): PromptEntrySummary {
  return { id, title, body: "", entry_type, metadata: {}, inputs: [], context_strategy: contextStrategy ?? null };
}

const ctx: PromptResolutionContext = {
  metadataSchema: SCHEMA,
  promptEntries: [],
  loreEntries: [],
  availableScenes: [],
};

const INLINE_CURSOR: PromptContextStrategy = { output: { handler: "inline" } };
const INLINE_SELECTION: PromptContextStrategy = {
  output: { handler: "inline", destination: "selection" },
};
const COMMIT: PromptContextStrategy = {
  output: { handler: "extract_to_node", commit: { review: "visual_diff" } },
};
const BROKEN: PromptContextStrategy = { output: { handler: "who_knows" } };

describe("dispositionFor — the five shelves (#951)", () => {
  it("maps each output disposition to its shelf", () => {
    expect(dispositionFor(ctx, prompt("a", "prompt:general", "a", INLINE_CURSOR)).label).toBe("Continue");
    expect(dispositionFor(ctx, prompt("b", "prompt:general", "b", INLINE_SELECTION)).label).toBe(
      "Revise prose",
    );
    expect(dispositionFor(ctx, prompt("c", "prompt:general")).label).toBe("Chat");
    expect(dispositionFor(ctx, prompt("d", "prompt:general", "d", COMMIT)).label).toBe(
      "Revise entities",
    );
  });

  it("shelves a no-contract prompt (and any unregistered handler) under Snippets", () => {
    // A snippet is uninvocable by entry_type alone (ADR-0065 S3) — the definition
    // of 'no invocation contract', regardless of context_strategy.
    expect(dispositionFor(ctx, prompt("e", "prompt:snippet")).label).toBe("Snippets");
    // A misconfigured instance (a non-empty but unregistered handler) can't be
    // invoked either → Snippets, not a crash.
    expect(dispositionFor(ctx, prompt("f", "prompt:general", "f", BROKEN)).label).toBe("Snippets");
    // A snippet stays uninvocable even if it happens to carry a context_strategy —
    // invocability is the entry_type, never the presence/shape of the strategy.
    expect(dispositionFor(ctx, prompt("g", "prompt:snippet", "g", INLINE_CURSOR)).label).toBe(
      "Snippets",
    );
  });

  it("has commit distinguish Revise entities from a plain Chat on the same chat_panel", () => {
    expect(dispositionFor(ctx, prompt("c", "prompt:general")).label).toBe("Chat");
    expect(dispositionFor(ctx, prompt("d", "prompt:general", "d", COMMIT)).label).toBe(
      "Revise entities",
    );
  });
});

describe("promptSummariesToGroupNodes — the pane lift", () => {
  it("stamps the disposition label into metadata for group_by to bucket on", () => {
    const [node] = promptSummariesToGroupNodes([prompt("a", "prompt:general", "a", INLINE_CURSOR)], SCHEMA);
    expect(node.metadata[DISPOSITION_FIELD]).toBe("Continue");
    // The summary's own fields survive the lift.
    expect(node.id).toBe("a");
    expect(node.entry_type).toBe("prompt:general");
  });

  it("clusters the roster into shelf order (first-seen == rank), preserving intra-shelf order", () => {
    // Deliberately interleaved input across shelves; snippet last regardless.
    const roster = [
      prompt("snip", "prompt:snippet"),
      prompt("gen", "prompt:general"),
      prompt("cont-b", "prompt:general", "Beta", INLINE_CURSOR),
      prompt("brainstorm", "prompt:general", "brainstorm", COMMIT),
      prompt("cont-a", "prompt:general", "Alpha", INLINE_CURSOR),
      prompt("revise", "prompt:general", "revise", INLINE_SELECTION),
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
    const original = prompt("a", "prompt:general", "a", INLINE_CURSOR);
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
      dispositionFor(ctx, prompt("d", "prompt:general", "d", COMMIT)).label,
    );
  });
});
