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
import type { PromptSurface } from "@/lib/editor-core/promptResolution";
import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";

// A schema whose `prompt:revise` type resolves as the entry_patch (brainstorm)
// surface — the set the ＋New menu offers.
const SCHEMA = {
  entry_types: {
    "prompt:revise": {
      name: "Revise",
      prompt: { context_strategy: { output: { kind: "entry_patch" } } },
    },
    // A chat-surface prompt — a different surface, so the panel's surface filter
    // must partition it out of an entry_patch ＋New (and vice versa).
    "prompt:scenechat": {
      name: "Scene chat",
      prompt: { context_strategy: { output: { kind: "chat_panel" } } },
    },
  },
  fields: {},
} as unknown as MetadataSchema;

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

function revisePrompt(id: string, title: string): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt:revise",
    metadata: {},
    inputs: [],
  } as unknown as PromptEntrySummary;
}

// An entry_patch (brainstorm) prompt whose `entry` input targets `targetType` —
// the per-node filter (ADR-0048 S8b) shows it only on a subject that is-a it.
function targetedPrompt(id: string, title: string, targetType: string): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt:revise",
    metadata: {},
    inputs: [
      { name: "entry", type: "context_pick", label: "E", target: { sources: [{ expr: { type: targetType } }] } },
    ],
  } as unknown as PromptEntrySummary;
}

function chatPanelPrompt(id: string, title: string): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt:scenechat",
    metadata: {},
    inputs: [],
  } as unknown as PromptEntrySummary;
}

function renderPanel(
  promptEntries: PromptEntrySummary[] = [],
  newSurface?: PromptSurface,
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
      ...(newSurface ? { newSurface } : {}),
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
    renderPanel([revisePrompt("p-revise", "Brainstorm a revision")]);

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

  it("folds '/'-titled prompts into a submenu the ＋New menu drills into (#832)", async () => {
    const spawn = vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue(undefined);
    renderPanel([
      revisePrompt("p-tone", "Revise/Tone"),
      revisePrompt("p-length", "Revise/Length"),
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
      revisePrompt("p-tone", "Revise/Tone"),
      revisePrompt("p-length", "Revise/Length"),
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
      revisePrompt("p-tone", "Revise/Tone"),
      revisePrompt("p-length", "Revise/Length"),
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

  it("offers exactly the prompts matching the requested surface (#842)", async () => {
    // The panel is surface-generic: it shows only prompts whose output kind
    // matches `newSurface`, and drops the rest. (Which surface a given subject
    // kind uses lives in NodeEditor — lore and scene both take entry_patch as of
    // S5-next; here we prove the filter itself, using chat_panel as the foil.)
    renderPanel(
      [revisePrompt("p-revise", "Brainstorm a revision"), chatPanelPrompt("p-chat", "Chat here")],
      "chat_panel",
    );
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    expect(screen.getByRole("menuitem", { name: "Chat here" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Brainstorm a revision" })).toBeNull();
  });

  it("hides ＋New when no prompt resolves to the requested surface (#842)", () => {
    // Only an entry_patch prompt is available but the requested surface is
    // chat_panel → nothing to start, so ＋New does not render (resume list only).
    const { container } = renderPanel([revisePrompt("p-revise", "Brainstorm a revision")], "chat_panel");
    expect(container.querySelector(".conv-new")).toBeNull();
    // The panel still renders — there are chats to resume.
    expect(container.querySelector(".entry-conversations")).not.toBeNull();
  });

  it("hides an entry_patch prompt whose target the subject is not (ADR-0048 S8b)", () => {
    // A plot-card-targeting brainstorm prompt on a LORE subject → excluded, so
    // ＋New has nothing to start (the resume list still renders).
    const { container } = renderPanel(
      [targetedPrompt("p-card", "Revise plot card", "plot:card")],
      undefined,
      "lore:character",
    );
    expect(container.querySelector(".conv-new")).toBeNull();
    expect(container.querySelector(".entry-conversations")).not.toBeNull();
  });

  it("shows an entry_patch prompt for a subject that is its target type (ADR-0048 S8b)", async () => {
    // The same prompt on a plot:card subject → offered.
    renderPanel([targetedPrompt("p-card", "Revise plot card", "plot:card")], undefined, "plot:card");
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    await tick();
    expect(screen.getByRole("menuitem", { name: "Revise plot card" })).toBeInTheDocument();
  });

  it("scopes a scene subject to scene-targeted brainstorms (ADR-0051 S5-next)", async () => {
    // A scene's entry_patch ＋New offers a scene-targeted prompt ("Summarize
    // scene") but not a lore-targeted one — scenes joined the loop at S5-next and
    // the same target filter keeps the lore prompts off the scene menu.
    renderPanel(
      [
        targetedPrompt("p-sum", "Summarize scene", "scene:scene"),
        targetedPrompt("p-lore", "Revise entry", "lore:base"),
      ],
      undefined,
      "scene:scene",
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
