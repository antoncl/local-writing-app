// @vitest-environment happy-dom
// ADR-0076 S7: the Context door's interior (head/body/drill) moved into
// ContextDoor.svelte — ChatComposerBar's popover now only positions it
// (`.cbv-preview-popover`) and owns the outside-click dismissal.
// ContextDoor.test.ts owns the deep per-panel drill assertions; this file is
// the integration smoke test — the door opens, the props actually reach
// ContextDoor (a tier row drills to its member entry and that entry's own
// rendered XML), and the System fallback chain still resolves through the
// wiring — proving the composer's prop-plumbing, not re-testing every leaf.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@/lib/test/component";
import ChatComposerBar from "./ChatComposerBar.svelte";
import type { ChangedPick, ChatSessionJournalEntry, PreviewCacheBlock } from "@/lib/types";

const BASE = "BASE-SYSTEM-PROMPT";

const baseProps = {
  isLocked: true,
  chatPromptEntryId: "prompt_1",
  chatAssistantId: "",
  promptEntries: [],
  routedPromptEntries: [],
  assistantEntries: [],
  assistantScope: [],
  scopedDefaultId: "",
  chatSystemPrompt: BASE,
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

const openPreview = async () =>
  fireEvent.click(screen.getByRole("button", { name: "Context — what will be sent" }));

describe("ChatComposerBar Context door", () => {
  it("opens the door at root, then drills System to the base system prompt", async () => {
    render(ChatComposerBar, baseProps);
    await openPreview();
    // The dialog's own panel title, distinct from the "Context" trigger chip.
    const dialog = screen.getByRole("dialog", { name: "Context — what will be sent" });
    expect(within(dialog).getByText("Context")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("System"));
    expect(screen.getByText(BASE)).toBeInTheDocument();
  });

  it("drills a lore tier down to its member entry and its rendered XML — previewCacheBlocks/titleFor reach ContextDoor", async () => {
    const blocks: PreviewCacheBlock[] = [
      { label: "system", role: "system", tokens: 12, tier: "stable", text: BASE },
      {
        label: "volatile lore",
        role: "system",
        tokens: 500,
        tier: "volatile",
        text: '<lore>\n<character id="lore_shenzhen">Shenzhen</character>\n</lore>',
        entry_ids: ["lore_shenzhen"],
        entry_xml: { lore_shenzhen: '<character id="lore_shenzhen">Shenzhen</character>' },
      },
    ];
    render(ChatComposerBar, {
      ...baseProps,
      previewCacheBlocks: blocks,
      titleFor: (id: string) => (id === "lore_shenzhen" ? "Shenzhen Protocol" : null),
    });
    await openPreview();
    await fireEvent.click(screen.getByText("volatile lore"));
    expect(screen.getByText("Shenzhen Protocol")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("Shenzhen Protocol"));
    expect(screen.getByText(/id="lore_shenzhen"/)).toBeInTheDocument();
  });

  it("falls back to the system prompt when there are no cache blocks", async () => {
    render(ChatComposerBar, { ...baseProps, previewCacheBlocks: [] });
    await openPreview();
    await fireEvent.click(screen.getByText("System"));
    expect(screen.getByText(BASE)).toBeInTheDocument();
  });
});
