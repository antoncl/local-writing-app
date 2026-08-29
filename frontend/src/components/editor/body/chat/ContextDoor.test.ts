// @vitest-environment happy-dom
// ADR-0076 S7: the Context door is now a true DRILL (root → tier → entry →
// its own rendered XML → back), not the old inline `<details>` expand. The
// discriminator vs. the retired expand: at root, an entry's title must be
// ABSENT from the document (behind a drill), not merely collapsed — an
// expand would still render it (hidden by CSS, still in the DOM); a drill
// doesn't mount it at all.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import ContextDoor from "./ContextDoor.svelte";
import type { ChatSessionJournalEntry, PreviewCacheBlock } from "@/lib/types";

const BASE = "BASE-SYSTEM-PROMPT";
const XML_A = '<character id="lore_a" name="A">…A…</character>';
const XML_B = '<character id="lore_b" name="B">…B…</character>';

const tierBlock: PreviewCacheBlock = {
  label: "volatile lore",
  role: "system",
  tokens: 500,
  tier: "volatile",
  text: `<lore>\n${XML_A}\n\n${XML_B}\n</lore>`,
  entry_ids: ["lore_a", "lore_b"],
  entry_xml: { lore_a: XML_A, lore_b: XML_B },
};

const titleFor = (id: string) => ({ lore_a: "A", lore_b: "B" })[id] ?? null;

const baseProps = {
  previewCacheBlocks: [] as PreviewCacheBlock[],
  chatPromptEntryId: "",
  chatSystemPrompt: BASE,
  chatPreviewMessages: null,
  loreEnabled: false,
  lockedInputDisplays: [] as { name: string; label: string; value: string }[],
  journal: [] as ChatSessionJournalEntry[],
  titleFor,
  onClose: () => {},
};

describe("ContextDoor", () => {
  it("shows the tier row at root, but NOT its member entries — the discriminator vs. the old expand", () => {
    render(ContextDoor, { ...baseProps, previewCacheBlocks: [tierBlock] });
    expect(screen.getByText("volatile lore")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
    expect(screen.queryByText(XML_A)).not.toBeInTheDocument();
  });

  it("drills the tier to its member entries, an entry to its own XML, then Back twice returns to root", async () => {
    render(ContextDoor, { ...baseProps, previewCacheBlocks: [tierBlock] });

    // Root -> tier: the entry titles now render; the other root rows (e.g.
    // System) are gone — only the panel head still says "volatile lore" (the
    // panel title), the root's ROW is what's retired.
    await fireEvent.click(screen.getByText("volatile lore"));
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("System")).not.toBeInTheDocument();

    // Tier -> entry A: its XML renders; B is gone.
    await fireEvent.click(screen.getByText("A"));
    expect(screen.getByText(XML_A)).toBeInTheDocument();
    expect(screen.queryByText("B")).not.toBeInTheDocument();
    expect(screen.queryByText(XML_B)).not.toBeInTheDocument();

    // Back -> the entry list again (A and B).
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText(XML_A)).not.toBeInTheDocument();

    // Back again -> root (the tier row, and System is reachable again).
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("volatile lore")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });

  it("has no Back button at root", () => {
    render(ContextDoor, { ...baseProps, previewCacheBlocks: [tierBlock] });
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("System row drills to the base system text; the lore-enabled annotation shows iff loreEnabled", async () => {
    const { unmount } = render(ContextDoor, { ...baseProps, loreEnabled: true });
    await fireEvent.click(screen.getByText("System"));
    expect(screen.getByText(BASE)).toBeInTheDocument();
    expect(screen.getByText("lore-enabled")).toBeInTheDocument();
    unmount();

    render(ContextDoor, { ...baseProps, loreEnabled: false });
    await fireEvent.click(screen.getByText("System"));
    expect(screen.getByText(BASE)).toBeInTheDocument();
    expect(screen.queryByText("lore-enabled")).not.toBeInTheDocument();
  });

  it("Inputs row drills to the locked kv pairs", async () => {
    render(ContextDoor, {
      ...baseProps,
      lockedInputDisplays: [{ name: "focus", label: "Focus", value: "upload-ethics thread" }],
    });
    expect(screen.getByText("Inputs (locked)")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("Inputs (locked)"));
    expect(screen.getByText("Focus")).toBeInTheDocument();
    expect(screen.getByText("upload-ethics thread")).toBeInTheDocument();
  });

  it("journal row drills to the roster", async () => {
    render(ContextDoor, {
      ...baseProps,
      journal: [{ entry_id: "lore_1", title: "Shenzhen Protocol", added_at_turn: 2 }],
    });
    await fireEvent.click(screen.getByText("Auto-added this conversation"));
    expect(screen.getByText(/Shenzhen Protocol/)).toBeInTheDocument();
    expect(screen.getByText(/turn 2/)).toBeInTheDocument();
  });

  it("with a prompt bound but nothing rendered yet, the System row guides the writer to fill inputs", async () => {
    render(ContextDoor, {
      ...baseProps,
      chatPromptEntryId: "p1",
      chatSystemPrompt: "",
      previewCacheBlocks: [],
      chatPreviewMessages: null,
    });
    await fireEvent.click(screen.getByText("System"));
    expect(
      screen.getByText("Fill the required inputs above and the assembled message will appear here."),
    ).toBeInTheDocument();
  });

  it("with no prompt bound and no system content, there is no System row at all", () => {
    render(ContextDoor, {
      ...baseProps,
      chatPromptEntryId: "",
      chatSystemPrompt: "",
      previewCacheBlocks: [],
      chatPreviewMessages: null,
    });
    expect(screen.queryByText("System")).not.toBeInTheDocument();
  });

  it("shows a defensive message when an entry carries no XML", async () => {
    const emptyEntryBlock: PreviewCacheBlock = {
      ...tierBlock,
      entry_ids: ["lore_a"],
      entry_xml: {},
    };
    render(ContextDoor, { ...baseProps, previewCacheBlocks: [emptyEntryBlock] });
    await fireEvent.click(screen.getByText("volatile lore"));
    await fireEvent.click(screen.getByText("A"));
    expect(screen.getByText("This entry rendered no XML.")).toBeInTheDocument();
  });
});
