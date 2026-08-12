// @vitest-environment happy-dom
// ADR-0051 S6 — the Chats pane is a designable View. This pins the WIRING the
// #724 empty-pane trap keeps re-opening (harness memo: "twice"): the roster
// flows through `evaluateView`, whose default chat membership is
// `descendants_of: chat:chat_session`. If a summary carried the old bare
// `entry_type: "chat"` stamp (or the schema root went missing), the designed
// view would filter every chat out and the pane would render empty — which the
// backend/API tests cannot see, because the drop is in the view layer. So this
// asserts the rows actually render, and that `subject` is reachable as a
// group/filter key (the marquee "group by subject").
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import Chats from "./Chats.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { builtinViews } from "@/lib/views/builtinViews";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary, ViewSpec } from "@/lib/types";

// The chat kind's root type + its `subject` field. `defaultView("chat", …)`
// resolves the roster to `descendants_of chat:chat_session` off this root; drop
// the type and evaluateView renders nothing (the very trap under test).
const SCHEMA = {
  entry_types: {
    "chat:chat_session": { name: "Chat", kind: "chat" },
  },
  fields: {
    subject: { name: "Subject", type: "entity_ref" },
  },
} as unknown as MetadataSchema;

function chat(id: string, title: string, subject = ""): ChatSessionSummary {
  return {
    id,
    title,
    entry_type: "chat:chat_session",
    subject,
    prompt_entry_id: "",
    assistant_id: "",
    pinned: false,
    created_at: "2026-01-01T00:00",
    updated_at: "2026-01-02T00:00",
    message_count: 3,
    cost_usd_total: 0,
  };
}

const noop = () => {};

function renderPane(sessions: ChatSessionSummary[], viewSpec: ViewSpec, promptEntries: PromptEntrySummary[] = []) {
  return render(Chats, {
    props: {
      sessions,
      viewSpec,
      activeChatId: null,
      promptEntries,
      assistantEntries: [],
      onOpenChat: noop,
      onDeleteChat: noop,
    },
  });
}

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
});

describe("Chats pane — designable view (ADR-0051 S6)", () => {
  it("renders every chat through the default view — the empty-pane guard", () => {
    // The default chat view is `descendants_of chat:chat_session`. A bare
    // `entry_type: "chat"` would not descend from it and both rows would vanish.
    renderPane([chat("chat_a", "Chat Alpha", "lore-a"), chat("chat_b", "Chat Beta", "lore-b")], defaultView("chat", SCHEMA));
    expect(screen.getByText("Chat Alpha")).toBeInTheDocument();
    expect(screen.getByText("Chat Beta")).toBeInTheDocument();
  });

  it("filters on subject — proving it is reachable as a designed key", () => {
    // A `subject set` filter keeps the chat that has a subject and drops the
    // freeform one. This only works if `subject` is present on the node's
    // metadata (fieldAccess routes non-intrinsic keys there, ADR-0029 §D).
    const spec: ViewSpec = {
      kind: "chat",
      expr: { filter: { of: { descendants_of: "chat:chat_session" }, pred: { field: { key: "subject", op: "set" } } } },
      sort: { by: "manual" },
    };
    renderPane([chat("chat_a", "Chat Alpha", "lore-a"), chat("chat_free", "Freeform Chat", "")], spec);
    expect(screen.getByText("Chat Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Freeform Chat")).toBeNull();
  });

  it("groups by subject — the marquee, partitioning rows into per-subject buckets", () => {
    // Two chats with distinct subjects land in two buckets keyed by the subject
    // value; the bucket headers carry those values. If `subject` were not on the
    // node's metadata, both would collapse into one empty bucket and neither
    // subject label would render.
    const spec: ViewSpec = {
      kind: "chat",
      expr: { descendants_of: "chat:chat_session" },
      sort: { by: "manual" },
      group_by: [{ field: "subject" }],
    };
    renderPane([chat("chat_a", "Chat Alpha", "lore-a"), chat("chat_b", "Chat Beta", "lore-b")], spec);
    // Both rows still render (grouping never drops members)...
    expect(screen.getByText("Chat Alpha")).toBeInTheDocument();
    expect(screen.getByText("Chat Beta")).toBeInTheDocument();
    // ...under two distinct subject-keyed bucket headers.
    expect(screen.getByText("lore-a")).toBeInTheDocument();
    expect(screen.getByText("lore-b")).toBeInTheDocument();
  });
});

describe("Chats pane — Openable built-in view (ADR-0051 S6 follow-up)", () => {
  // Extend the schema with the two prompt types that decide openability.
  const OPENABLE_SCHEMA = {
    entry_types: {
      "chat:chat_session": { name: "Chat", kind: "chat" },
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

  function seededChat(id: string, title: string, promptId: string): ChatSessionSummary {
    return { ...chat(id, title), prompt_entry_id: promptId };
  }

  it("hides the brainstorm (entry_patch) chat, keeps General + freeform", () => {
    metadataSchemaStore.set(OPENABLE_SCHEMA);
    const spec = builtinViews("chat", OPENABLE_SCHEMA)[1].spec; // "Openable chats"
    renderPane(
      [
        seededChat("c_general", "General Chat", "p_general"),
        seededChat("c_brainstorm", "Brainstorm Chat", "p_revise"),
        chat("c_free", "Freeform Chat"), // no seeding prompt
      ],
      spec,
      [prompt("p_general", "prompt:general"), prompt("p_revise", "prompt:revise:entry")],
    );
    expect(screen.getByText("General Chat")).toBeInTheDocument();
    expect(screen.getByText("Freeform Chat")).toBeInTheDocument();
    // The brainstorm chat (output kind entry_patch) is filtered out.
    expect(screen.queryByText("Brainstorm Chat")).toBeNull();
  });
});
