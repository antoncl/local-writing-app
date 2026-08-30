// @vitest-environment happy-dom
// ADR-0076 S6: proves the title-field snippet seam is actually wired — a
// trivial snippet passed as `titleField` renders inside the composer strip,
// as the first item sharing the row with the setup chips.
import { describe, expect, it } from "vitest";
import { createRawSnippet } from "svelte";
import { render, screen } from "@/lib/test/component";
import ChatComposerBar from "./ChatComposerBar.svelte";
import type { ChangedPick, ChatSessionJournalEntry, PreviewCacheBlock, PromptEntrySummary } from "@/lib/types";

const baseProps = {
  isLocked: false,
  chatPromptEntryId: "",
  chatAssistantId: "",
  promptEntries: [] as PromptEntrySummary[],
  routedPromptEntries: [] as PromptEntrySummary[],
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

describe("ChatComposerBar titleField", () => {
  it("renders a passed titleField snippet inside the composer strip", () => {
    const titleField = createRawSnippet(() => ({
      render: () => `<input class="title-input" value="Elias's arc" />`,
    }));
    render(ChatComposerBar, { ...baseProps, titleField });
    expect(screen.getByDisplayValue("Elias's arc")).toBeInTheDocument();
  });
});
