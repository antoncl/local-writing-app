import { describe, expect, it } from "vitest";
import { chatSummariesToEvalNodes, seedDispositionFieldDef } from "./chatNodes";
import type { ChatSessionSummary, MetadataSchema, PromptContextStrategy, PromptEntrySummary } from "@/lib/types";

// A placeholder, non-null schema — openability is decided by each prompt
// INSTANCE's own `context_strategy` now (ADR-0065 S3), set directly below: the
// brainstorm declares a `commit` (ADR-0054 §2), the plain chat does not.
const SCHEMA = {
  entry_types: {},
  fields: {},
} as unknown as MetadataSchema;

function prompt(
  id: string,
  entryType: string,
  contextStrategy?: PromptContextStrategy | null,
): PromptEntrySummary {
  return {
    id,
    title: id,
    body: "",
    entry_type: entryType,
    metadata: {},
    inputs: [],
    context_strategy: contextStrategy ?? null,
    source_layer_id: "layer_project",
    source_layer_label: "Project",
    is_library: false,
  } as unknown as PromptEntrySummary;
}

const COMMIT_STRATEGY: PromptContextStrategy = {
  output: { handler: "extract_to_node", commit: { review: "visual_diff" } },
};

function chat(id: string, promptId: string, subject = ""): ChatSessionSummary {
  return {
    id,
    title: id,
    entry_type: "chat:chat_session",
    subject,
    prompt_entry_id: promptId,
    assistant_id: "",
    pinned: false,
    created_at: "2026-01-01T00:00",
    updated_at: "2026-01-01T00:00",
    message_count: 0,
    cost_usd_total: 0,
  };
}

describe("chatSummariesToEvalNodes (ADR-0051 S6 follow-up)", () => {
  const prompts = [prompt("p_general", "prompt:general"), prompt("p_revise", "prompt:general", COMMIT_STRATEGY)];

  it("derives seed_disposition from the seeding prompt's disposition label", () => {
    const nodes = chatSummariesToEvalNodes(
      [chat("c_general", "p_general"), chat("c_brainstorm", "p_revise")],
      prompts,
      SCHEMA,
    );
    const byId = new Map(nodes.map((n) => [n.id, n]));
    expect(byId.get("c_general")?.metadata.seed_disposition).toBe("Chat"); // plain chat_panel
    expect(byId.get("c_brainstorm")?.metadata.seed_disposition).toBe("Revise entities"); // chat_panel + commit
  });

  it("leaves a freeform chat (no prompt) empty — the openable default", () => {
    const [node] = chatSummariesToEvalNodes([chat("c_free", "")], prompts, SCHEMA);
    expect(node.metadata.seed_disposition).toBe("");
  });

  it("places subject in metadata alongside the derived disposition", () => {
    const [node] = chatSummariesToEvalNodes([chat("c", "p_general", "lore-a")], prompts, SCHEMA);
    expect(node.metadata.subject).toBe("lore-a");
    expect(node.entry_type).toBe("chat:chat_session");
  });
});

describe("seedDispositionFieldDef — the designer computed field (#960)", () => {
  it("is a computed select offering the two chat_panel dispositions the lift can stamp", () => {
    const def = seedDispositionFieldDef();
    expect(def.type).toBe("select");
    expect(def.category).toBe("computed");
    expect(def.options.map((o) => o.value)).toEqual(["Chat", "Revise entities"]);
    // The stamped values are exactly these choices, so a designer filter matches.
    const nodes = chatSummariesToEvalNodes(
      [chat("g", "p_general"), chat("b", "p_revise")],
      [prompt("p_general", "prompt:general"), prompt("p_revise", "prompt:general", COMMIT_STRATEGY)],
      SCHEMA,
    );
    const stamped = nodes.map((n) => n.metadata.seed_disposition);
    for (const value of stamped) expect(def.options.map((o) => o.value)).toContain(value);
  });
});
