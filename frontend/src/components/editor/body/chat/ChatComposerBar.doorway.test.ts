// @vitest-environment happy-dom
// ADR-0076 S4: the lock doorway. A locked chip used to be inert (tooltip
// only) — clicking it now opens a small popover with a one-line constraint
// and ONE action, "New chat with this setup", that creates a fresh chat
// seeded with the same prompt/assistant/input drafts (never the transcript).
// This guards the doorway's core promise: it opens ONLY when locked with a
// bound prompt, and a non-locked chip still opens its picker (regression).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import ChatComposerBar from "./ChatComposerBar.svelte";
import type { ChangedPick, ChatSessionJournalEntry, PreviewCacheBlock, PromptEntrySummary } from "@/lib/types";

// The doorway gates on the bound prompt RESOLVING in this roster (a deleted
// prompt must not offer a no-op button), so a matching entry has to be present.
const PROMPT_ROSTER = [
  { id: "p1", title: "Draft prompt", entry_type: "prompt" },
] as unknown as PromptEntrySummary[];

// The routed pick list feeding the prompt chip's PromptMenu — a plain leaf
// plus one with a "/" in its title, to exercise the group drill.
const ROUTED_PROMPTS = [
  { id: "p1", title: "Draft prompt", entry_type: "prompt" },
  { id: "p2", title: "Revise/Tone", entry_type: "prompt" },
] as unknown as PromptEntrySummary[];

const baseProps = {
  isLocked: true,
  chatPromptEntryId: "p1",
  chatAssistantId: "a1",
  promptEntries: PROMPT_ROSTER,
  routedPromptEntries: ROUTED_PROMPTS,
  assistantEntries: [],
  assistantScope: [],
  scopedDefaultId: "",
  chatSystemPrompt: "",
  chatPreviewMessages: null,
  previewCacheBlocks: [] as PreviewCacheBlock[],
  loreEnabled: false,
  journal: [] as ChatSessionJournalEntry[],
  changedPicks: [] as ChangedPick[],
  onOpenDoor: () => {},
  lockedInputDisplays: [] as { name: string; label: string; value: string }[],
  titleFor: (_id: string) => null as string | null,
  onPickPrompt: () => {},
  onPickAssistant: () => {},
  onNewChatWithSetup: () => {},
};

describe("ChatComposerBar lock doorway", () => {
  it("opens the doorway from the locked prompt chip, with the prompt wording and action", async () => {
    const onNewChatWithSetup = vi.fn();
    render(ChatComposerBar, { ...baseProps, onNewChatWithSetup });
    await fireEvent.click(screen.getByTitle("Prompt is locked while this chat has messages."));
    expect(
      screen.getByText("Locked after the first message — this prompt shapes every turn."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat with this setup" })).toBeInTheDocument();
  });

  it("calls onNewChatWithSetup exactly once when the action is clicked", async () => {
    const onNewChatWithSetup = vi.fn();
    render(ChatComposerBar, { ...baseProps, onNewChatWithSetup });
    await fireEvent.click(screen.getByTitle("Prompt is locked while this chat has messages."));
    await fireEvent.click(screen.getByRole("button", { name: "New chat with this setup" }));
    expect(onNewChatWithSetup).toHaveBeenCalledTimes(1);
  });

  it("opens the doorway from the locked assistant chip, with the assistant wording", async () => {
    render(ChatComposerBar, { ...baseProps });
    await fireEvent.click(screen.getByTitle("Assistant is locked while this chat has messages."));
    expect(
      screen.getByText("Locked after the first message — this assistant answers every turn."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat with this setup" })).toBeInTheDocument();
  });

  it("regression: an unlocked prompt chip opens the PromptMenu, not the doorway", async () => {
    render(ChatComposerBar, { ...baseProps, isLocked: false });
    await fireEvent.click(screen.getByTitle("Pick a prompt"));
    expect(
      screen.queryByText("Locked after the first message — this prompt shapes every turn."),
    ).not.toBeInTheDocument();
    // "Draft prompt" has no "/" so it stays a flat leaf; "Revise/Tone" collapses
    // into a drillable "Revise" group row (ADR-0076 S5's `/`-tree, not a flat
    // search list — the search field is gone).
    expect(screen.getByRole("menuitem", { name: "Draft prompt" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Revise" })).toBeInTheDocument();
  });

  it("drills into a grouped prompt title and picking the leaf calls onPickPrompt", async () => {
    const onPickPrompt = vi.fn();
    render(ChatComposerBar, { ...baseProps, isLocked: false, onPickPrompt });
    await fireEvent.click(screen.getByTitle("Pick a prompt"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise" }));
    const leaf = screen.getByRole("menuitem", { name: "Tone" });
    expect(leaf).toBeInTheDocument();
    await fireEvent.click(leaf);
    expect(onPickPrompt).toHaveBeenCalledTimes(1);
    expect(onPickPrompt).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p2", title: "Revise/Tone" }),
    );
  });

  it("does not offer the doorway when the bound prompt no longer resolves", async () => {
    // A locked chat whose prompt was deleted: chatPromptEntryId is set but the
    // roster can't resolve it, so the action (openChatFromPromptEntry) can't run
    // — the doorway must NOT appear rather than show a no-op button.
    render(ChatComposerBar, { ...baseProps, promptEntries: [] });
    await fireEvent.click(screen.getByTitle("Prompt is locked while this chat has messages."));
    expect(
      screen.queryByText("Locked after the first message — this prompt shapes every turn."),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New chat with this setup" })).not.toBeInTheDocument();
  });
});
