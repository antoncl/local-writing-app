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
import type { ChangedPick, ChatSessionJournalEntry, LoreFit, PreviewCacheBlock } from "@/lib/types";

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
  changedPicks: [] as ChangedPick[],
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

  it("#1635: changedPicks alone (no journal) shows the auto-added row with count 1, and drilling shows the edited marker", async () => {
    render(ContextDoor, {
      ...baseProps,
      journal: [],
      changedPicks: [{ id: "lore-1", title: "Avatar" }],
    });
    const row = screen.getByText("Auto-added this conversation").closest("button");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("1");
    await fireEvent.click(screen.getByText("Auto-added this conversation"));
    expect(screen.getByText(/Avatar/)).toBeInTheDocument();
    expect(screen.getByText("edited")).toBeInTheDocument();
  });

  it("#1635: journal + changedPicks sum in the count and both render when drilled", async () => {
    render(ContextDoor, {
      ...baseProps,
      journal: [{ entry_id: "lore_1", title: "Shenzhen Protocol", added_at_turn: 2 }],
      changedPicks: [{ id: "lore-1", title: "Avatar" }],
    });
    const row = screen.getByText("Auto-added this conversation").closest("button");
    expect(row).toHaveTextContent("2");
    await fireEvent.click(screen.getByText("Auto-added this conversation"));
    expect(screen.getByText(/Shenzhen Protocol/)).toBeInTheDocument();
    expect(screen.getByText(/Avatar/)).toBeInTheDocument();
    expect(screen.getByText("edited")).toBeInTheDocument();
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

  // ADR-0086 S2: the "Left out" section — what the last send's lore budget
  // left out (or the turn-0 preview's, before the first send), each entry with
  // its source and size, drillable to its element like a tier's entry.
  const LEFT_OUT_FIT: LoreFit = {
    budget_tokens: 16000,
    used_tokens: 15800,
    declared_tokens: 2100,
    kept: 21,
    left_out: [
      { id: "lore_c", title: "Keros's tolls", source: "depth1_expansion", tokens: 900 },
      { id: "lore_d", title: "The Honey Jar", source: "structural_hop", tokens: 400 },
    ],
  };
  const XML_C = '<place id="lore_c" name="Keros\'s tolls">…C…</place>';

  it("shows no Left out row when the fit left nothing out and the declared set fits", () => {
    const fitted: LoreFit = { ...LEFT_OUT_FIT, left_out: [], declared_tokens: 100 };
    render(ContextDoor, { ...baseProps, loreFit: fitted });
    expect(screen.queryByText("Left out")).not.toBeInTheDocument();
  });

  it("lists the left-out entries with source and size behind a drill, using the preview's XML when it has it", async () => {
    render(ContextDoor, {
      ...baseProps,
      loreFit: LEFT_OUT_FIT,
      loreLeftOutXml: { lore_c: XML_C },
    });
    // Root: the row with its count and total size; the entries themselves are
    // behind the drill, not in the DOM.
    expect(screen.getByText("Left out")).toBeInTheDocument();
    expect(screen.getByText(/2 entries · 1\.3k tok/)).toBeInTheDocument();
    expect(screen.queryByText("Keros's tolls")).not.toBeInTheDocument();

    await fireEvent.click(screen.getByText("Left out"));
    expect(screen.getByText(/lore 15\.8k\/16k/)).toBeInTheDocument();
    expect(screen.getByText("Keros's tolls")).toBeInTheDocument();
    expect(screen.getByText(/one hop · mention · 900 tok/)).toBeInTheDocument();
    expect(screen.getByText("The Honey Jar")).toBeInTheDocument();
    expect(screen.getByText(/one hop · link · 400 tok/)).toBeInTheDocument();
    // The two moves the author has, named in the door.
    expect(screen.getByText(/Always include/)).toBeInTheDocument();
    // Not a warning: the declared set fits, so no "over the budget" line.
    expect(screen.queryByText(/over the/)).not.toBeInTheDocument();

    await fireEvent.click(screen.getByText("Keros's tolls"));
    expect(screen.getByText(XML_C)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("The Honey Jar")).toBeInTheDocument();
  });

  it("renders a sent turn's left-out entry on request through fetchLeftOutXml", async () => {
    const asked: string[] = [];
    const fetchLeftOutXml = async (id: string) => {
      asked.push(id);
      return `<place id="${id}" name="fetched">…</place>`;
    };
    render(ContextDoor, { ...baseProps, loreFit: LEFT_OUT_FIT, fetchLeftOutXml });
    await fireEvent.click(screen.getByText("Left out"));
    await fireEvent.click(screen.getByText("The Honey Jar"));
    expect(await screen.findByText('<place id="lore_d" name="fetched">…</place>')).toBeInTheDocument();
    expect(asked).toEqual(["lore_d"]);
    // Drilling the same entry again does not ask again.
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await fireEvent.click(screen.getByText("The Honey Jar"));
    expect(asked).toEqual(["lore_d"]);
  });

  it("states a declared set over a non-zero budget, and never for a budget of 0", async () => {
    const over: LoreFit = { ...LEFT_OUT_FIT, left_out: [], declared_tokens: 30200 };
    render(ContextDoor, { ...baseProps, loreFit: over });
    expect(screen.getByText("declared over budget")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("Left out"));
    expect(screen.getByText(/declared lore 30\.2k, over the 16k budget/)).toBeInTheDocument();

    const declaredOnly: LoreFit = { ...over, budget_tokens: 0, used_tokens: 0 };
    // Scoped to this render's container — the first render above is still
    // mounted with "Left out" as its drilled panel title.
    const zero = render(ContextDoor, { ...baseProps, loreFit: declaredOnly });
    expect(zero.container.textContent).not.toContain("Left out");
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
