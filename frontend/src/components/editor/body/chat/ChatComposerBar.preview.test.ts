// @vitest-environment happy-dom
// The 👁 preview popover is a data-displaying surface (#642): it must render the
// ATTACHED LORE the model will actually receive, not just the base system
// prompt. The lore lives only in a send-path cache block (use_lore() emits
// nothing into the template), so dropping the block's text — as the estimate
// strip does — left the preview looking empty even though 5k of lore was being
// sent (#1546 follow-up). This guards that the block text is shown.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import ChatComposerBar from "./ChatComposerBar.svelte";
import type { PreviewCacheBlock } from "@/lib/types";

const LORE = "SHENZHEN-LORE-SENTINEL";
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
  onPickPrompt: () => {},
  onPickAssistant: () => {},
};

const openPreview = async () =>
  fireEvent.click(screen.getByRole("button", { name: "Preview what's sent" }));

describe("ChatComposerBar preview popover", () => {
  it("renders the attached lore cache block, not just the system prompt", async () => {
    const blocks: PreviewCacheBlock[] = [
      { label: "system", role: "system", tokens: 12, tier: "stable", text: BASE },
      { label: "volatile lore", role: "system", tokens: 500, tier: "volatile", text: LORE },
    ];
    render(ChatComposerBar, { ...baseProps, previewCacheBlocks: blocks });
    await openPreview();
    // The lore the model receives is visible — the whole point of the preview.
    expect(screen.getByText(LORE)).toBeInTheDocument();
    expect(screen.getByText(BASE)).toBeInTheDocument();
  });

  it("falls back to the system prompt when there are no cache blocks", async () => {
    render(ChatComposerBar, { ...baseProps, previewCacheBlocks: [] });
    await openPreview();
    expect(screen.getByText(BASE)).toBeInTheDocument();
  });
});
