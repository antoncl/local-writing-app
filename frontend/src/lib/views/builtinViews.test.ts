import { describe, expect, it } from "vitest";
import { builtinViews, builtinSpecFor, isBuiltinExtraViewId } from "./builtinViews";
import { chatSummariesToEvalNodes } from "./chatNodes";
import { promptSummariesToGroupNodes } from "./promptNodes";
import { evaluateView } from "./evaluateView";
import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";

const CHAT_SCHEMA = {
  entry_types: { "chat:chat_session": { name: "Chat", kind: "chat" } },
  fields: {},
} as unknown as MetadataSchema;

// A schema carrying the chat root — the seed disposition the lift resolves against
// is read off each prompt INSTANCE's own `context_strategy` now (ADR-0065 S3), set
// directly on the fixtures below: a plain general (chat) vs one that commits
// (→ "Revise entities"). Used for the end-to-end evaluate below.
const EVAL_SCHEMA = {
  entry_types: {
    "chat:chat_session": { name: "Chat", kind: "chat" },
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

  it("ships two built-in views for prompt: All prompts + Runnable prompts", () => {
    const views = builtinViews("prompt", null);
    expect(views.map((v) => v.title)).toEqual(["All prompts", "Runnable prompts"]);
    expect(views[0].id).toBe("view_default_prompt");
    expect(isBuiltinExtraViewId(views[1].id)).toBe(true);
    // Filters on the `runnable` flag the Prompts lift stamps, via overlap (a set op).
    const pred = views[1].spec.expr?.filter?.pred?.field;
    expect(pred?.key).toBe("runnable");
    expect(pred?.op).toBe("overlap");
    expect(pred?.value).toEqual(["runnable"]);
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
    {
      id: "p_revise",
      title: "Revise",
      body: "",
      entry_type: "prompt:general",
      metadata: {},
      inputs: [],
      context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } },
    },
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

// End-to-end: the "Runnable prompts" spec run through the real evaluator over
// lifted prompt nodes — proving the stamped `runnable` flag is genuinely
// filterable, not just present in the spec (mirrors the chat case above).
describe("Runnable prompts — evaluated over lifted prompts end to end (#1433)", () => {
  const PROMPT_EVAL_SCHEMA = {
    entry_types: {
      "prompt:base": { name: "Prompt" },
      "prompt:general": { name: "General", parent: "prompt:base" },
    },
    fields: {
      title: { name: "Title", type: "text", category: "intrinsic" },
      entry_type: { name: "Type", type: "text", category: "intrinsic" },
      id: { name: "ID", type: "text", category: "intrinsic" },
    },
  } as unknown as MetadataSchema;

  const p = (id: string, extra: Partial<PromptEntrySummary> = {}): PromptEntrySummary =>
    ({ id, title: id, body: "", entry_type: "prompt:general", metadata: {}, inputs: [], ...extra }) as unknown as PromptEntrySummary;
  const nodes = promptSummariesToGroupNodes(
    [
      p("p_chat"), // Chat, no offer_on → runnable
      p("p_impersonate", { offer_on: ["lore:character"] }), // Chat + offer_on → not
      p("p_continue", { context_strategy: { output: { handler: "inline" } } }), // Continue → not
    ],
    PROMPT_EVAL_SCHEMA,
  );

  it("keeps only the standalone-runnable prompt (Chat, empty offer_on)", () => {
    const spec = builtinViews("prompt", PROMPT_EVAL_SCHEMA)[1].spec;
    const kept = evaluateView(spec, nodes, { schema: PROMPT_EVAL_SCHEMA }).nodes.map((n) => n.id);
    expect(kept).toEqual(["p_chat"]);
  });
});
