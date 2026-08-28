// @vitest-environment happy-dom
// ADR-0076 S2: the 👁 preview popover became the worded, drillable Context
// door — the one place that answers "what will the AI see". This guards the
// door's core promise: the ATTACHED LORE the model will actually receive is
// visible (not just the base system prompt — the lore lives only in a
// send-path cache block, use_lore() emits nothing into the template, #1546
// follow-up), each tier drills down to its member entries by title (decision
// 2), and the sections absorbed from the retired inputs-strip/journal-scope
// strips (lore-enabled gate, locked inputs, auto-added journal) render.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import ChatComposerBar from "./ChatComposerBar.svelte";
import type { ChatSessionJournalEntry, PreviewCacheBlock } from "@/lib/types";

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
  loreEnabled: false,
  journal: [] as ChatSessionJournalEntry[],
  lockedInputDisplays: [] as { label: string; value: string }[],
  titleFor: (_id: string) => null as string | null,
  onPickPrompt: () => {},
  onPickAssistant: () => {},
};

const openPreview = async () =>
  fireEvent.click(screen.getByRole("button", { name: "Context — what will be sent" }));

describe("ChatComposerBar Context door", () => {
  it("drills a lore tier down to its member entries, by title, and shows the lore text", async () => {
    const blocks: PreviewCacheBlock[] = [
      { label: "system", role: "system", tokens: 12, tier: "stable", text: BASE },
      {
        label: "volatile lore",
        role: "system",
        tokens: 500,
        tier: "volatile",
        text: LORE,
        entry_ids: ["lore_shenzhen"],
      },
    ];
    render(ChatComposerBar, {
      ...baseProps,
      previewCacheBlocks: blocks,
      titleFor: (id: string) => (id === "lore_shenzhen" ? "Shenzhen Protocol" : null),
    });
    await openPreview();
    // The base system message is always shown.
    expect(screen.getByText(BASE)).toBeInTheDocument();
    // Expand the volatile tier by clicking its summary. (happy-dom doesn't
    // implement native <details> collapse — it can't assert the member title
    // is HIDDEN pre-expand, only that clicking the summary is the drill-down
    // gesture and the member title + lore text are both reachable through it.)
    await fireEvent.click(screen.getByText("volatile lore"));
    expect(screen.getByText("Shenzhen Protocol")).toBeInTheDocument();
    expect(screen.getByText(LORE)).toBeInTheDocument();
  });

  it("falls back to the system prompt when there are no cache blocks", async () => {
    render(ChatComposerBar, { ...baseProps, previewCacheBlocks: [] });
    await openPreview();
    expect(screen.getByText(BASE)).toBeInTheDocument();
  });

  it("shows the lore-enabled annotation iff loreEnabled", async () => {
    const { unmount } = render(ChatComposerBar, { ...baseProps, loreEnabled: true });
    await openPreview();
    expect(screen.getByText("lore-enabled")).toBeInTheDocument();
    unmount();

    render(ChatComposerBar, { ...baseProps, loreEnabled: false });
    await openPreview();
    expect(screen.queryByText("lore-enabled")).not.toBeInTheDocument();
  });

  it("renders the locked-inputs display pairs", async () => {
    render(ChatComposerBar, {
      ...baseProps,
      lockedInputDisplays: [{ label: "Focus", value: "upload-ethics thread" }],
    });
    await openPreview();
    expect(screen.getByText("Inputs (locked)")).toBeInTheDocument();
    expect(screen.getByText("Focus")).toBeInTheDocument();
    expect(screen.getByText("upload-ethics thread")).toBeInTheDocument();
  });

  it("renders a journal entry with its turn", async () => {
    render(ChatComposerBar, {
      ...baseProps,
      journal: [{ entry_id: "lore_1", title: "Shenzhen Protocol", added_at_turn: 2 }],
    });
    await openPreview();
    expect(screen.getByText("Auto-added this conversation")).toBeInTheDocument();
    expect(screen.getByText(/Shenzhen Protocol/)).toBeInTheDocument();
    expect(screen.getByText(/turn 2/)).toBeInTheDocument();
  });
});
