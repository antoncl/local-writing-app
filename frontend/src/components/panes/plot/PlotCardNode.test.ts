// @vitest-environment happy-dom
// PlotCardNode RENDER guard (ADR-0048 S7b). The plot board's job is to DISPLAY
// cards, and a display surface needs a mount test that asserts the content renders
// ([[reference_component_test_harness]] — the #724 lesson, twice). The board's
// SvelteFlow canvas is not headless-mountable, so this card is written WITHOUT any
// @xyflow/svelte import precisely so it can be mounted here on its own.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotCardNode from "./PlotCardNode.svelte";
import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";
import type { PlotCardData } from "@/lib/plot/plotBoardLayout";
import type { PlotBoardBeat, TemplateInstanceSummary } from "@/lib/types";

const beat = (over: Partial<PlotBoardBeat> = {}): PlotBoardBeat => ({
  instance_id: "i1",
  instance_title: "Hero's Journey",
  beat_id: "b1",
  title: "Call to Adventure",
  ...over,
});

const arcFixture = (beats: { id: string; title: string }[] = [{ id: "b1", title: "Call to Adventure" }]): TemplateInstanceSummary => ({
  id: "i1",
  title: "Hero's Journey",
  body: "",
  entry_type: "plot:template_instance",
  metadata: { instance_beats: beats },
});

const data = (over: Partial<PlotCardData> = {}): PlotCardData => ({
  title: "She leaves home",
  synopsis: "The heroine packs a bag and walks out.",
  attached: false,
  color: null,
  pageStatus: null,
  beats: [],
  causalLinks: [],
  ...over,
});

function actions(
  plotlines: PlotCardActions["plotlines"] = [],
  arcs: PlotCardActions["arcs"] = [],
  cards: PlotCardActions["cards"] = [],
): PlotCardActions {
  return {
    onOpen: vi.fn(),
    onRealize: vi.fn(),
    onDetach: vi.fn(),
    onEditTitle: vi.fn(),
    onEditSynopsis: vi.fn(),
    onSetPlotline: vi.fn(),
    onSetBeats: vi.fn(),
    onSetCausal: vi.fn(),
    onSetPageStatus: vi.fn(),
    plotlines,
    arcs,
    cards,
  };
}

function renderWithActions(over: Partial<PlotCardData>, acts: PlotCardActions, id = "card_1") {
  return render(PlotCardNode, { props: { id, data: data(over) }, context: new Map([[PLOT_CARD_ACTIONS, acts]]) });
}

describe("PlotCardNode", () => {
  it("renders the card title and synopsis", () => {
    render(PlotCardNode, { props: { data: data() } });
    expect(screen.getByText("She leaves home")).toBeInTheDocument();
    expect(screen.getByText("The heroine packs a bag and walks out.")).toBeInTheDocument();
  });

  it("shows the on-page marker for an attached card", () => {
    render(PlotCardNode, { props: { data: data({ attached: true, pageStatus: "on_page" }) } });
    expect(screen.getByText("On the page")).toBeInTheDocument();
  });

  it("shows the unwritten marker for a fresh unattached card", () => {
    render(PlotCardNode, { props: { data: data({ attached: false, pageStatus: null }) } });
    expect(screen.getByText("Unwritten")).toBeInTheDocument();
  });

  it("falls back to a placeholder title for an untitled card", () => {
    render(PlotCardNode, { props: { data: data({ title: "" }) } });
    expect(screen.getByText("Untitled card")).toBeInTheDocument();
  });

  // Without the actions context (S7b read-only board + this mount test's default),
  // the card exposes no kebab — unchanged from the read-only slice.
  it("shows no action menu when the actions context is absent", () => {
    render(PlotCardNode, { props: { data: data() } });
    expect(screen.queryByLabelText("Card actions")).toBeNull();
  });
});

describe("PlotCardNode — content-op menu (S7d)", () => {
  it("opens a menu with Open card + Realize scene for an unattached card", async () => {
    renderWithActions({ attached: false }, actions());
    await fireEvent.click(screen.getByLabelText("Card actions"));
    expect(screen.getByRole("menuitem", { name: "Open card" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Realize scene" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Detach scene" })).toBeNull();
  });

  it("offers Detach (not Realize) for an attached card", async () => {
    renderWithActions({ attached: true }, actions());
    await fireEvent.click(screen.getByLabelText("Card actions"));
    expect(screen.getByRole("menuitem", { name: "Detach scene" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Realize scene" })).toBeNull();
  });

  it("realizes via the card id", async () => {
    const acts = actions();
    renderWithActions({ attached: false }, acts, "card_9");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Realize scene" }));
    expect(acts.onRealize).toHaveBeenCalledWith("card_9");
  });

  it("opens the card editor via the card id", async () => {
    const acts = actions();
    renderWithActions({ attached: true }, acts, "card_2");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Open card" }));
    expect(acts.onOpen).toHaveBeenCalledWith("card_2");
  });

  it("renames the card in place and commits the change on blur", async () => {
    const acts = actions();
    renderWithActions({ title: "Old name" }, acts, "card_t1");
    await fireEvent.click(screen.getByRole("button", { name: "Old name" }));
    const input = screen.getByPlaceholderText("Card name") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "New name" } });
    await fireEvent.blur(input);
    expect(acts.onEditTitle).toHaveBeenCalledWith("card_t1", "New name");
  });

  it("does not save an emptied title (the backend requires a non-empty name)", async () => {
    const acts = actions();
    renderWithActions({ title: "Keep" }, acts, "card_t2");
    await fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    const input = screen.getByPlaceholderText("Card name") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "   " } });
    await fireEvent.blur(input);
    expect(acts.onEditTitle).not.toHaveBeenCalled();
  });

  it("Escape cancels the title edit without committing", async () => {
    const acts = actions();
    renderWithActions({ title: "Original" }, acts, "card_t3");
    await fireEvent.click(screen.getByRole("button", { name: "Original" }));
    const input = screen.getByPlaceholderText("Card name") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "discard" } });
    await fireEvent.keyDown(input, { key: "Escape" });
    await fireEvent.blur(input);
    expect(acts.onEditTitle).not.toHaveBeenCalled();
  });

  it("edits the synopsis in place and commits the change on blur", async () => {
    const acts = actions();
    renderWithActions({ synopsis: "old" }, acts, "card_3");
    await fireEvent.click(screen.getByRole("button", { name: "old" }));
    const box = screen.getByPlaceholderText("Add a synopsis…") as HTMLTextAreaElement;
    await fireEvent.input(box, { target: { value: "new synopsis" } });
    await fireEvent.blur(box);
    expect(acts.onEditSynopsis).toHaveBeenCalledWith("card_3", "new synopsis");
  });

  it("does not re-save an unchanged synopsis whose body has a trailing newline", async () => {
    // The projection synopsis is the raw body, stored with a trailing "\n"; a blur
    // with no edit must not fire a save (it would churn forever otherwise).
    const acts = actions();
    renderWithActions({ synopsis: "unchanged\n" }, acts, "card_6");
    await fireEvent.click(screen.getByRole("button", { name: "unchanged" }));
    const box = screen.getByPlaceholderText("Add a synopsis…") as HTMLTextAreaElement;
    await fireEvent.blur(box);
    expect(acts.onEditSynopsis).not.toHaveBeenCalled();
  });

  it("Escape cancels the synopsis edit without committing", async () => {
    const acts = actions();
    renderWithActions({ synopsis: "keep me" }, acts, "card_7");
    await fireEvent.click(screen.getByRole("button", { name: "keep me" }));
    const box = screen.getByPlaceholderText("Add a synopsis…") as HTMLTextAreaElement;
    await fireEvent.input(box, { target: { value: "discard this" } });
    await fireEvent.keyDown(box, { key: "Escape" });
    await fireEvent.blur(box);
    expect(acts.onEditSynopsis).not.toHaveBeenCalled();
  });

  it("reassigns the plotline from the Set-plotline submenu", async () => {
    const acts = actions([
      { id: "pl_a", title: "Main plot", color: null },
      { id: "pl_b", title: "Romance", color: null },
    ]);
    renderWithActions({ attached: false }, acts, "card_4");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    // Second page lists the lanes + Unassigned.
    await fireEvent.click(screen.getByRole("menuitem", { name: "Romance" }));
    expect(acts.onSetPlotline).toHaveBeenCalledWith("card_4", "pl_b");
  });

  it("clears the plotline via Unassigned", async () => {
    const acts = actions([{ id: "pl_a", title: "Main plot", color: null }]);
    renderWithActions({ attached: false }, acts, "card_5");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Unassigned" }));
    expect(acts.onSetPlotline).toHaveBeenCalledWith("card_5", "");
  });
});

describe("PlotCardNode — beats + page marker (S7 Slice 5b)", () => {
  it("renders a badge for each beat the card fulfils", () => {
    render(PlotCardNode, {
      props: { data: data({ beats: [beat({ beat_id: "b1", title: "Call to Adventure" }), beat({ beat_id: "b2", title: "Refusal" })] }) },
    });
    expect(screen.getByText("Call to Adventure")).toBeInTheDocument();
    expect(screen.getByText("Refusal")).toBeInTheDocument();
  });

  it("caps the badges and shows a +N overflow chip instead of hiding beats silently", () => {
    const many = Array.from({ length: 6 }, (_, i) => beat({ beat_id: `b${i}`, title: `Beat ${i}` }));
    render(PlotCardNode, { props: { data: data({ beats: many }) } });
    expect(screen.getByText("Beat 0")).toBeInTheDocument();
    expect(screen.getByText("Beat 3")).toBeInTheDocument(); // first 4 shown
    expect(screen.queryByText("Beat 4")).toBeNull(); // capped
    expect(screen.getByText("+2")).toBeInTheDocument(); // the overflow is visible
  });

  it("shows the on-page marker when page_status is on_page", () => {
    render(PlotCardNode, { props: { data: data({ pageStatus: "on_page" }) } });
    expect(screen.getByText("On the page")).toBeInTheDocument();
  });

  it("shows the off-page marker when page_status is off_page", () => {
    render(PlotCardNode, { props: { data: data({ pageStatus: "off_page" }) } });
    expect(screen.getByText("Off the page")).toBeInTheDocument();
  });

  it("falls back to the unwritten marker when page_status is null", () => {
    render(PlotCardNode, { props: { data: data({ pageStatus: null }) } });
    expect(screen.getByText("Unwritten")).toBeInTheDocument();
  });

  it("offers Mark off-page for an unattached unwritten card", async () => {
    const acts = actions();
    renderWithActions({ attached: false, pageStatus: null }, acts, "card_p1");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Mark off-page" }));
    expect(acts.onSetPageStatus).toHaveBeenCalledWith("card_p1", "off_page");
  });

  it("offers Mark unwritten for an off-page card, and reverts it", async () => {
    const acts = actions();
    renderWithActions({ attached: false, pageStatus: "off_page" }, acts, "card_p2");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Mark unwritten" }));
    expect(acts.onSetPageStatus).toHaveBeenCalledWith("card_p2", "unwritten");
  });

  it("hides the page-status toggle for an attached card (on_page is derived)", async () => {
    const acts = actions();
    renderWithActions({ attached: true, pageStatus: "on_page" }, acts);
    await fireEvent.click(screen.getByLabelText("Card actions"));
    expect(screen.queryByRole("menuitem", { name: /Mark (off-page|unwritten)/ })).toBeNull();
  });

  it("opens the beat picker and links a checked beat on leaving the page", async () => {
    const acts = actions([], [arcFixture([{ id: "b1", title: "Call to Adventure" }])]);
    renderWithActions({ beats: [] }, acts, "card_bk");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Beats/ }));
    await fireEvent.click(screen.getByRole("checkbox")); // link the beat
    await fireEvent.click(screen.getByRole("button", { name: /Beats/ })); // back → commit
    expect(acts.onSetBeats).toHaveBeenCalledWith("card_bk", [{ instance: "i1", beat_id: "b1" }]);
  });

  it("does not save when the beat selection is unchanged", async () => {
    const acts = actions([], [arcFixture([{ id: "b1", title: "Call to Adventure" }])]);
    renderWithActions({ beats: [beat({ beat_id: "b1" })] }, acts, "card_bn");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Beats/ }));
    await fireEvent.click(screen.getByRole("button", { name: /Beats/ })); // back with no toggle
    expect(acts.onSetBeats).not.toHaveBeenCalled();
  });

  it("commits beat edits when the menu is dismissed via the kebab button", async () => {
    // Closing the menu with the kebab (not the back arrow) must still flush the draft
    // — otherwise beat toggles are silently lost.
    const acts = actions([], [arcFixture([{ id: "b1", title: "Call to Adventure" }])]);
    renderWithActions({ beats: [] }, acts, "card_kb");
    const kebab = screen.getByRole("button", { name: "Card actions" }); // not the menu div
    await fireEvent.click(kebab); // open
    await fireEvent.click(screen.getByRole("menuitem", { name: /Beats/ })); // beats page
    await fireEvent.click(screen.getByRole("checkbox")); // link the beat
    await fireEvent.click(kebab); // close via kebab
    expect(acts.onSetBeats).toHaveBeenCalledWith("card_kb", [{ instance: "i1", beat_id: "b1" }]);
  });

  it("pre-checks a beat the card already fulfils in the picker", async () => {
    const acts = actions([], [arcFixture([{ id: "b1", title: "Call to Adventure" }])]);
    renderWithActions({ beats: [beat({ beat_id: "b1" })] }, acts, "card_bc");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Beats/ }));
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });
});

describe("PlotCardNode — causal links (S7 Slice 6b)", () => {
  const others = [
    { id: "other", title: "The storm hits" },
    { id: "third", title: "They reconcile" },
  ];

  it("opens the “Leads to…” picker and links a checked card on leaving the page", async () => {
    const acts = actions([], [], others);
    renderWithActions({ causalLinks: [] }, acts, "card_a");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Leads to/ }));
    await fireEvent.click(screen.getAllByRole("checkbox")[0]); // link "other"
    await fireEvent.click(screen.getByRole("button", { name: /Leads to/ })); // back → commit
    expect(acts.onSetCausal).toHaveBeenCalledWith("card_a", ["other"]);
  });

  it("does not save when the causal selection is unchanged", async () => {
    const acts = actions([], [], others);
    renderWithActions({ causalLinks: ["other"] }, acts, "card_b");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Leads to/ }));
    await fireEvent.click(screen.getByRole("button", { name: /Leads to/ })); // back with no toggle
    expect(acts.onSetCausal).not.toHaveBeenCalled();
  });

  it("commits causal edits when the menu is dismissed via the kebab button", async () => {
    const acts = actions([], [], others);
    renderWithActions({ causalLinks: [] }, acts, "card_kb");
    const kebab = screen.getByRole("button", { name: "Card actions" });
    await fireEvent.click(kebab); // open
    await fireEvent.click(screen.getByRole("menuitem", { name: /Leads to/ }));
    await fireEvent.click(screen.getAllByRole("checkbox")[0]); // link "other"
    await fireEvent.click(kebab); // close via kebab flushes the draft
    expect(acts.onSetCausal).toHaveBeenCalledWith("card_kb", ["other"]);
  });

  it("pre-checks a target the card already leads to, and excludes itself", async () => {
    const acts = actions([], [], [{ id: "card_pc", title: "Self" }, ...others]);
    renderWithActions({ causalLinks: ["other"] }, acts, "card_pc");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Leads to/ }));
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes).toHaveLength(2); // self filtered out of the 3 cards
    expect(boxes[0].checked).toBe(true); // "other", already linked
    expect(boxes[1].checked).toBe(false); // "third"
  });
});
