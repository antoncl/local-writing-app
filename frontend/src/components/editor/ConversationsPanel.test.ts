// @vitest-environment happy-dom
// The Conversations surface (ADR-0051 S3). `conversationsFor` is unit-tested
// beside it; this pins the PANEL's own contract — that the reverse-ref ∩ roster
// set actually RENDERS as rows (the #642 lesson: a view-layer filter can
// silently empty a data pane), that clicking a row RESUMES (openChat) rather
// than spawning, and that ＋New is the explicit spawn path (openChatFromPromptEntry
// with the subject stamped).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import ConversationsPanel from "./ConversationsPanel.svelte";
import { chatSessionsStore } from "@/lib/stores/chats";
import { referenceIndexStore } from "@/lib/stores/references";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import type { ChatSessionSummary, MetadataSchema, PromptContextStrategy, PromptEntrySummary } from "@/lib/types";

// ADR-0065 S3: a prompt's disposition is its own INSTANCE `context_strategy`, not
// a schema-type lookup — so the fixtures below (chatPrompt / revisePlotline) set
// it directly. Under the offer_on model (ADR-0054 §4/S4) both a committing
// brainstorm and a plain conversation (e.g. impersonate) are offerable — commit
// is orthogonal; what gates the ＋New menu is the `conversation` surface plus an
// `offer_on` allow-list that admits the subject. An inline (non-conversation)
// strategy is used to prove the eligibility gate.
const SCHEMA = { entry_types: {}, fields: {} } as unknown as MetadataSchema;

const INLINE_STRATEGY: PromptContextStrategy = { output: { handler: "inline" } };

function chat(over: Partial<ChatSessionSummary>): ChatSessionSummary {
  return {
    id: "c",
    title: "Chat",
    entry_type: "chat:chat_session",
    prompt_entry_id: "",
    assistant_id: "",
    pinned: false,
    created_at: "2026-08-01T00:00:00",
    updated_at: "2026-08-01T00:00:00",
    message_count: 0,
    ...over,
  };
}

// A prompt declaring which subject types it is offered on (ADR-0054 §4/S4). The
// instance's own `context_strategy` picks the disposition (ADR-0065 S3): absent
// (default here) is a plain conversation (commit orthogonal to eligibility, so a
// committing brainstorm needs no different fixture); `INLINE_STRATEGY` is
// append_to_body (never a conversation). Membership in the ＋New menu is
// `offer_on` + the `conversation` surface.
function chatPrompt(
  id: string,
  title: string,
  offerOn: string[],
  contextStrategy?: PromptContextStrategy | null,
): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [],
    offer_on: offerOn,
    context_strategy: contextStrategy ?? null,
  } as unknown as PromptEntrySummary;
}

function renderPanel(
  promptEntries: PromptEntrySummary[] = [],
  subjectEntryType = "lore:character",
) {
  return render(ConversationsPanel, {
    props: {
      subjectId: "hero",
      subjectTitle: "Hero",
      subjectEntryType,
      promptEntries,
      metadataSchema: SCHEMA,
      hostPaneId: "pane-1",
    },
  });
}

beforeEach(() => {
  // Two chats are about "hero", one is not; the reverse index says which.
  chatSessionsStore.set([
    chat({ id: "recent", title: "Recent brainstorm", updated_at: "2026-08-10T09:00:00", message_count: 4 }),
    chat({ id: "older", title: "Older brainstorm", updated_at: "2026-08-02T09:00:00", message_count: 2 }),
    chat({ id: "unrelated", title: "About someone else" }),
  ]);
  referenceIndexStore.set(new Map([["hero", new Set(["recent", "older"])]]));
});
afterEach(() => {
  chatSessionsStore.set([]);
  referenceIndexStore.set(new Map());
  vi.restoreAllMocks();
});

describe("ConversationsPanel (ADR-0051 S3)", () => {
  it("renders the chats about this node and excludes unrelated ones", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: /Recent brainstorm/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Older brainstorm/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /About someone else/ })).toBeNull();
  });

  it("resumes an existing thread on row click instead of spawning", async () => {
    const openChat = vi.spyOn(editorPanes, "openChat").mockResolvedValue(undefined);
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    renderPanel();

    await fireEvent.click(screen.getByRole("button", { name: /Recent brainstorm/ }));
    expect(openChat).toHaveBeenCalledWith("recent");
    expect(spawn).not.toHaveBeenCalled();
  });

  it("＋New spawns a chat with this node stamped as the subject", async () => {
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    renderPanel([chatPrompt("p-revise", "Brainstorm a revision", ["lore:character"])]);

    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Brainstorm a revision" }));

    expect(spawn).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p-revise" }),
      { entry: "hero" },
      null,
      expect.objectContaining({ subject: "hero", subjectTitle: "Hero", parentPaneId: "pane-1" }),
    );
  });

  it("seeds a context_pick `entry` target as an array-shaped ref, not a bare id (#1094)", async () => {
    // The real revise prompts declare `entry` as a required context_pick (an
    // array of NodePickerRefs). A bare-id seed made isInputMissing throw, so a
    // plotline/plot-card revise failed "Missing required" on send. The subject's
    // kind is the FQN prefix of its entry_type.
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    const revisePlotline = {
      id: "p-revise-plotline",
      title: "Revise plotline",
      body: "",
      entry_type: "prompt:general",
      metadata: {},
      inputs: [{ name: "entry", type: "context_pick", label: "Plotline", required: true }],
      offer_on: ["plot:plotline"],
    } as unknown as PromptEntrySummary;
    renderPanel([revisePlotline], "plot:plotline");

    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise plotline" }));

    expect(spawn).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p-revise-plotline" }),
      { entry: [{ id: "hero", kind: "plot", title: "Hero", entry_type: "plot:plotline" }] },
      null,
      expect.objectContaining({ subject: "hero", subjectTitle: "Hero" }),
    );
  });

  it("seeds the slider's scene onto the prompt's as_of input (ADR-0055 §1)", async () => {
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    render(ConversationsPanel, {
      props: {
        subjectId: "hero",
        subjectTitle: "Hero",
        subjectEntryType: "lore:character",
        asOfScene: "scene_ch12",
        promptEntries: [chatPrompt("p-imp", "Impersonate", ["lore:character"])],
        metadataSchema: SCHEMA,
        hostPaneId: "pane-1",
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Impersonate" }));

    expect(spawn).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p-imp" }),
      { entry: "hero", as_of: "scene_ch12" },
      null,
      expect.objectContaining({ subject: "hero" }),
    );
  });

  it("omits as_of when the slider is at book-start, keeping inputs clean", async () => {
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    // renderPanel leaves asOfScene at its "" default (base / book-start).
    renderPanel([chatPrompt("p-imp", "Impersonate", ["lore:character"])]);
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Impersonate" }));

    expect(spawn).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p-imp" }),
      { entry: "hero" },
      null,
      expect.anything(),
    );
  });

  it("folds '/'-titled prompts into a submenu the ＋New menu drills into (#832)", async () => {
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    renderPanel([
      chatPrompt("p-tone", "Revise/Tone", ["lore:character"]),
      chatPrompt("p-length", "Revise/Length", ["lore:character"]),
    ]);

    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    // Two prompts sharing the "Revise" prefix collapse into one group entry.
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise" }));
    await tick();
    // Drilled in: the leaves are reachable, the group entry is gone.
    expect(screen.queryByRole("menuitem", { name: "Revise" })).toBeNull();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Tone" }));

    expect(spawn).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p-tone" }),
      { entry: "hero" },
      null,
      expect.objectContaining({ subject: "hero" }),
    );
  });

  it("moves focus onto the submenu's first item when drilling in (#832)", async () => {
    renderPanel([
      chatPrompt("p-tone", "Revise/Tone", ["lore:character"]),
      chatPrompt("p-length", "Revise/Length", ["lore:character"]),
    ]);
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise" }));
    await tick();
    // The activated group button unmounted; focus must land on the first child
    // (alpha: "Length") rather than falling to <body> — otherwise the drilled-in
    // menu is unreachable by keyboard.
    expect(screen.getByRole("menuitem", { name: "Length" })).toHaveFocus();
  });

  it("ascends one level on Escape while drilled in, keeping the menu open (#832)", async () => {
    renderPanel([
      chatPrompt("p-tone", "Revise/Tone", ["lore:character"]),
      chatPrompt("p-length", "Revise/Length", ["lore:character"]),
    ]);
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise" }));
    await tick();
    expect(screen.queryByRole("menuitem", { name: "Revise" })).toBeNull();

    // Escape on a submenu item ascends (does NOT bubble to the Popover's window
    // listener, which would close the whole menu). The "Revise" group re-appearing
    // proves both: the level ascended AND the Popover stayed open.
    await fireEvent.keyDown(screen.getByRole("menuitem", { name: "Length" }), { key: "Escape" });
    await tick();
    expect(screen.getByRole("menuitem", { name: "Revise" })).toBeInTheDocument();
  });

  it("offers both committing and plain chat_panel prompts — commit is orthogonal (ADR-0054 §4/S4)", async () => {
    // The ＋New shows every chat_panel prompt whose offer_on admits the subject;
    // a plain conversation (no commit, e.g. impersonate) is offered alongside a
    // committing brainstorm. This is the S4 behaviour change from the old
    // commit-only filter (#842).
    renderPanel([
      chatPrompt("p-revise", "Brainstorm a revision", ["lore:character"]),
      chatPrompt("p-chat", "Chat here", ["lore:character"]),
    ]);
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    expect(screen.getByRole("menuitem", { name: "Brainstorm a revision" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Chat here" })).toBeInTheDocument();
  });

  it("excludes a non-chat_panel prompt even when its offer_on matches (eligibility axis)", () => {
    // An append_to_body prompt is launched from the editor, never a card's ＋New;
    // declaring offer_on on it must not surface it here. Nothing else to start →
    // ＋New hides (resume list still renders).
    const { container } = renderPanel([
      chatPrompt("p-inline", "Inline draft", ["lore:character"], INLINE_STRATEGY),
    ]);
    expect(container.querySelector(".conv-new")).toBeNull();
    expect(container.querySelector(".entry-conversations")).not.toBeNull();
  });

  it("hides ＋New when no prompt is offered on this subject (ADR-0054 §4/S4)", () => {
    // A chat prompt whose offer_on does not admit this subject → nothing to
    // start, so ＋New does not render (resume list only).
    const { container } = renderPanel([chatPrompt("p-chat", "Chat here", ["plot:card"])]);
    expect(container.querySelector(".conv-new")).toBeNull();
    // The panel still renders — there are chats to resume.
    expect(container.querySelector(".entry-conversations")).not.toBeNull();
  });

  it("hides a prompt whose offer_on the subject is not (ADR-0054 §4/S4)", () => {
    // A plot-card prompt on a LORE subject → excluded, so ＋New has nothing to
    // start (the resume list still renders).
    const { container } = renderPanel(
      [chatPrompt("p-card", "Revise plot card", ["plot:card"])],
      "lore:character",
    );
    expect(container.querySelector(".conv-new")).toBeNull();
    expect(container.querySelector(".entry-conversations")).not.toBeNull();
  });

  it("shows a prompt for a subject its offer_on admits (ADR-0054 §4/S4)", async () => {
    // The same prompt on a plot:card subject → offered.
    renderPanel([chatPrompt("p-card", "Revise plot card", ["plot:card"])], "plot:card");
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    expect(screen.getByRole("menuitem", { name: "Revise plot card" })).toBeInTheDocument();
  });

  it("scopes a scene subject to scene-offered prompts (ADR-0054 §4/S4)", async () => {
    // A scene's ＋New offers a scene-scoped prompt ("Summarize scene") but not a
    // lore-scoped one — offer_on keeps the lore prompts off the scene menu.
    renderPanel(
      [
        chatPrompt("p-sum", "Summarize scene", ["manuscript:scene"]),
        chatPrompt("p-lore", "Revise entry", ["lore:base"]),
      ],
      "manuscript:scene",
    );
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    expect(screen.getByRole("menuitem", { name: "Summarize scene" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Revise entry" })).toBeNull();
  });

  it("does not render when there is nothing to resume and no prompt to start", () => {
    referenceIndexStore.set(new Map());
    const { container } = renderPanel();
    expect(container.querySelector(".entry-conversations")).toBeNull();
  });
});
