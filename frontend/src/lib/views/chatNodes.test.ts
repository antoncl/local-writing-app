import { describe, expect, it } from "vitest";
import { chatSummariesToEvalNodes, seedDispositionFieldDef } from "./chatNodes";
import type { ChatSessionSummary, PromptEntrySummary } from "@/lib/types";

// The seed's disposition is the BACKEND-stamped computed value on the prompt
// summary (#1684) — the lift just resolves `prompt_entry_id` through the roster
// and copies it. Fixtures therefore carry `computed_metadata` the way the
// backend stamps it, not a `context_strategy` to re-derive from.
function prompt(id: string, disposition: string): PromptEntrySummary {
  return {
    id,
    title: id,
    body: "",
    entry_type: "prompt:general",
    metadata: {},
    computed_metadata: { disposition, runnable: "" },
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
  const prompts = [prompt("p_general", "Chat"), prompt("p_revise", "Revise entities")];

  it("copies the seeding prompt's backend-stamped disposition into seed_disposition", () => {
    const nodes = chatSummariesToEvalNodes(
      [chat("c_general", "p_general"), chat("c_brainstorm", "p_revise")],
      prompts,
    );
    const byId = new Map(nodes.map((n) => [n.id, n]));
    expect(byId.get("c_general")?.metadata.seed_disposition).toBe("Chat");
    expect(byId.get("c_brainstorm")?.metadata.seed_disposition).toBe("Revise entities");
  });

  it("leaves a freeform chat (no prompt) empty — the openable default", () => {
    const [node] = chatSummariesToEvalNodes([chat("c_free", "")], prompts);
    expect(node.metadata.seed_disposition).toBe("");
  });

  it("leaves a chat whose prompt summary carries no stamp empty (older backend)", () => {
    // Deliberately out of the type contract (computed_metadata is required) —
    // the runtime read must still degrade to "" rather than crash.
    const unstamped = {
      ...prompt("p_old", "Chat"),
      computed_metadata: undefined,
    } as unknown as PromptEntrySummary;
    const [node] = chatSummariesToEvalNodes([chat("c", "p_old")], [unstamped]);
    expect(node.metadata.seed_disposition).toBe("");
  });

  it("places subject in metadata alongside the derived disposition", () => {
    const [node] = chatSummariesToEvalNodes([chat("c", "p_general", "lore-a")], prompts);
    expect(node.metadata.subject).toBe("lore-a");
    expect(node.entry_type).toBe("chat:chat_session");
  });
});

describe("seedDispositionFieldDef — the designer computed field (#960)", () => {
  it("is a computed select offering the two conversation dispositions the lift can stamp", () => {
    const def = seedDispositionFieldDef();
    expect(def.type).toBe("select");
    expect(def.category).toBe("computed");
    expect(def.options.map((o) => o.value)).toEqual(["Chat", "Revise entities"]);
    // The stamped values are exactly these choices, so a designer filter matches.
    const nodes = chatSummariesToEvalNodes(
      [chat("g", "p_general"), chat("b", "p_revise")],
      [prompt("p_general", "Chat"), prompt("p_revise", "Revise entities")],
    );
    const stamped = nodes.map((n) => n.metadata.seed_disposition);
    for (const value of stamped) expect(def.options.map((o) => o.value)).toContain(value);
  });
});
