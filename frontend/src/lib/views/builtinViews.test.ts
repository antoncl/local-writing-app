import { describe, expect, it } from "vitest";
import { builtinViews, builtinSpecFor, isBuiltinExtraViewId } from "./builtinViews";
import { chatSummariesToEvalNodes } from "./chatNodes";
import { evaluateView } from "./evaluateView";
import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";

const CHAT_SCHEMA = {
  entry_types: { "chat:chat_session": { name: "Chat", kind: "chat" } },
  fields: {},
} as unknown as MetadataSchema;

// A schema carrying both the chat root and the prompt types the lift resolves a
// seed disposition against — general (chat_panel) vs revise:entry (chat_panel +
// commit → "Revise entities"). Used for the end-to-end evaluate below.
const EVAL_SCHEMA = {
  entry_types: {
    "chat:chat_session": { name: "Chat", kind: "chat" },
    "prompt:general": { name: "General", kind: "prompt", prompt: { context_strategy: {} } },
    "prompt:revise:entry": {
      name: "Revise entry",
      kind: "prompt",
      prompt: { context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } } },
    },
  },
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    id: { name: "ID", type: "text", category: "intrinsic" },
  },
} as unknown as MetadataSchema;

describe("builtinViews (ADR-0051 S6 follow-up)", () => {
  it("ships two built-in views for chat: All chats + Openable", () => {
    const views = builtinViews("chat", CHAT_SCHEMA);
    expect(views.map((v) => v.title)).toEqual(["All chats", "Openable chats"]);
    // [0] is the roster default addressed by the fold-state id.
    expect(views[0].id).toBe("view_default_chat");
    // The extra is a synthesized built-in, recognised as a valid selection.
    expect(isBuiltinExtraViewId(views[1].id)).toBe(true);
    expect(isBuiltinExtraViewId(views[0].id)).toBe(false);
  });

  it("Openable filters out the brainstorm chats (seed disposition Revise entities) via disjoint", () => {
    const openable = builtinViews("chat", CHAT_SCHEMA)[1].spec;
    const pred = openable.expr?.filter?.pred?.field;
    expect(pred?.key).toBe("seed_disposition");
    expect(pred?.op).toBe("disjoint");
    expect(pred?.value).toEqual(["Revise entities"]);
  });

  it("every other kind ships a single default view (defaultView parity untouched)", () => {
    const lore = builtinViews("lore", null);
    expect(lore).toHaveLength(1);
    expect(lore[0].title).toBe("Default view");
    expect(lore[0].id).toBe("view_default_lore");
  });

  it("builtinSpecFor resolves a built-in id, else null", () => {
    expect(builtinSpecFor("chat", "view_builtin_chat_openable", CHAT_SCHEMA)).not.toBeNull();
    expect(builtinSpecFor("chat", "view_default_chat", CHAT_SCHEMA)).not.toBeNull();
    expect(builtinSpecFor("chat", "view_some_user_view", CHAT_SCHEMA)).toBeNull();
  });
});

// End-to-end: the same seed_disposition predicate a user would author in the
// designer, run through the real evaluator over lifted chat nodes. Proves the field
// is genuinely filterable — not just present in a spec (#960).
describe("Openable chats — evaluated over lifted chats end to end (#960)", () => {
  const prompts: PromptEntrySummary[] = [
    { id: "p_general", title: "General", body: "", entry_type: "prompt:general", metadata: {}, inputs: [] },
    { id: "p_revise", title: "Revise", body: "", entry_type: "prompt:revise:entry", metadata: {}, inputs: [] },
  ] as unknown as PromptEntrySummary[];
  const chat = (id: string, promptId: string): ChatSessionSummary =>
    ({ id, title: id, entry_type: "chat:chat_session", subject: "", prompt_entry_id: promptId }) as unknown as ChatSessionSummary;
  const nodes = chatSummariesToEvalNodes(
    [chat("c_general", "p_general"), chat("c_brainstorm", "p_revise"), chat("c_free", "")],
    prompts,
    EVAL_SCHEMA,
  );

  it("keeps general + freeform chats and drops the brainstorm one", () => {
    const spec = builtinViews("chat", EVAL_SCHEMA)[1].spec;
    const kept = evaluateView(spec, nodes, { schema: EVAL_SCHEMA }).nodes.map((n) => n.id);
    expect(kept.sort()).toEqual(["c_free", "c_general"]);
  });

  it("the inverted predicate (overlap) selects exactly the brainstorm chats — a designable 'Brainstorm chats' view", () => {
    const spec = builtinViews("chat", EVAL_SCHEMA)[1].spec;
    const inverted = structuredClone(spec);
    inverted.expr!.filter!.pred!.field!.op = "overlap";
    const kept = evaluateView(inverted, nodes, { schema: EVAL_SCHEMA }).nodes.map((n) => n.id);
    expect(kept).toEqual(["c_brainstorm"]);
  });
});
