import { describe, expect, it } from "vitest";
import { chatSummariesToEvalNodes } from "./chatNodes";
import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";

// A schema whose prompt types carry the output kinds that decide openability.
const SCHEMA = {
  entry_types: {
    "prompt:general": { name: "General", kind: "prompt", prompt: { context_strategy: { output: { kind: "chat_panel" } } } },
    "prompt:revise:entry": {
      name: "Revise entry",
      kind: "prompt",
      prompt: { context_strategy: { output: { kind: "entry_patch" } } },
    },
  },
  fields: {},
} as unknown as MetadataSchema;

function prompt(id: string, entryType: string): PromptEntrySummary {
  return {
    id,
    title: id,
    body: "",
    entry_type: entryType,
    metadata: {},
    inputs: [],
    source_layer_id: "layer_project",
    source_layer_label: "Project",
    is_library: false,
  } as unknown as PromptEntrySummary;
}

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
  const prompts = [prompt("p_general", "prompt:general"), prompt("p_revise", "prompt:revise:entry")];

  it("derives seed_output_kind from the seeding prompt's output kind", () => {
    const nodes = chatSummariesToEvalNodes(
      [chat("c_general", "p_general"), chat("c_brainstorm", "p_revise")],
      prompts,
      SCHEMA,
    );
    const byId = new Map(nodes.map((n) => [n.id, n]));
    expect(byId.get("c_general")?.metadata.seed_output_kind).toBe("chat_panel");
    expect(byId.get("c_brainstorm")?.metadata.seed_output_kind).toBe("entry_patch");
  });

  it("leaves a freeform chat (no prompt) empty — the openable default", () => {
    const [node] = chatSummariesToEvalNodes([chat("c_free", "")], prompts, SCHEMA);
    expect(node.metadata.seed_output_kind).toBe("");
  });

  it("places subject in metadata alongside the derived kind", () => {
    const [node] = chatSummariesToEvalNodes([chat("c", "p_general", "lore-a")], prompts, SCHEMA);
    expect(node.metadata.subject).toBe("lore-a");
    expect(node.entry_type).toBe("chat:chat_session");
  });
});
