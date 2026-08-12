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
import type { PlotBoardBeat } from "@/lib/types";
import { PLOT_DND_MIME } from "@/lib/plot/plotDnd";

const beat = (over: Partial<PlotBoardBeat> = {}): PlotBoardBeat => ({
  instance_id: "i1",
  instance_title: "Hero's Journey",
  beat_id: "b1",
  title: "Call to Adventure",
  ...over,
});

const data = (over: Partial<PlotCardData> = {}): PlotCardData => ({
  title: "She leaves home",
  synopsis: "The heroine packs a bag and walks out.",
  attached: false,
  color: null,
  plotlineId: null,
  plotlineName: null,
  pageStatus: null,
  beats: [],
  causalLinks: [],
  ...over,
});

function actions(plotlines: PlotCardActions["plotlines"] = []): PlotCardActions {
  return {
    onOpen: vi.fn(),
    onRealize: vi.fn(),
    onDetach: vi.fn(),
    onEditTitle: vi.fn(),
    onEditSynopsis: vi.fn(),
    onSetPlotline: vi.fn(),
    onLinkBeat: vi.fn(),
    onUnlinkBeat: vi.fn(),
    onSetPageStatus: vi.fn(),
    onDelete: vi.fn(),
    plotlines,
  };
}

// A stand-in DataTransfer carrying a beat drag (or, with mime="", a foreign drag).
function beatDataTransfer(instance: string, beatId: string): DataTransfer {
  const store: Record<string, string> = {
    [PLOT_DND_MIME]: JSON.stringify({ kind: "beat", instance, beat_id: beatId }),
  };
  return {
    types: Object.keys(store),
    getData: (t: string) => store[t] ?? "",
    setData: (t: string, v: string) => void (store[t] = v),
    dropEffect: "none",
    effectAllowed: "all",
  } as unknown as DataTransfer;
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

  it("names the plotline on the card, and omits the chip when unassigned (#863)", () => {
    const { unmount } = render(PlotCardNode, { props: { data: data({ plotlineName: "Romance" }) } });
    expect(screen.getByText("Romance")).toBeInTheDocument();
    unmount();
    render(PlotCardNode, { props: { data: data({ plotlineName: null }) } });
    expect(screen.queryByText("Romance")).toBeNull();
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

  it("deletes the card via the card id (#860)", async () => {
    const acts = actions();
    renderWithActions({ attached: false }, acts, "card_9");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Delete card" }));
    expect(acts.onDelete).toHaveBeenCalledWith("card_9");
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

  it("marks the card's current plotline in the submenu (#863)", async () => {
    const acts = actions([
      { id: "pl_a", title: "Main plot", color: null },
      { id: "pl_b", title: "Romance", color: null },
    ]);
    renderWithActions({ attached: false, plotlineId: "pl_b", plotlineName: "Romance" }, acts, "card_6");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    expect(screen.getByRole("menuitem", { name: "Romance", current: true })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Main plot" })).not.toHaveAttribute("aria-current", "true");
  });

  it("marks Unassigned as current when the card has no plotline (#863)", async () => {
    const acts = actions([{ id: "pl_a", title: "Main plot", color: null }]);
    renderWithActions({ attached: false, plotlineId: null }, acts, "card_7");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    expect(screen.getByRole("menuitem", { name: "Unassigned", current: true })).toBeInTheDocument();
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

  it("has no Beats / Leads-to menu items (those are drag gestures now, #824)", async () => {
    renderWithActions({ beats: [] }, actions());
    await fireEvent.click(screen.getByLabelText("Card actions"));
    expect(screen.queryByRole("menuitem", { name: /Beats/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Leads to/ })).toBeNull();
  });
});

describe("PlotCardNode — beat linking by drag (S7 #824)", () => {
  it("links a beat dropped from the palette onto the card", async () => {
    const acts = actions();
    const { container } = renderWithActions({ beats: [] }, acts, "card_d1");
    const card = container.querySelector(".plot-card") as HTMLElement;
    const dataTransfer = beatDataTransfer("i1", "b1");
    await fireEvent.dragOver(card, { dataTransfer });
    await fireEvent.drop(card, { dataTransfer });
    expect(acts.onLinkBeat).toHaveBeenCalledWith("card_d1", "i1", "b1");
  });

  it("ignores a drop that carries no beat payload", async () => {
    const acts = actions();
    const { container } = renderWithActions({ beats: [] }, acts, "card_d2");
    const card = container.querySelector(".plot-card") as HTMLElement;
    const foreign = { types: ["text/plain"], getData: () => "", setData: () => {} } as unknown as DataTransfer;
    await fireEvent.drop(card, { dataTransfer: foreign });
    expect(acts.onLinkBeat).not.toHaveBeenCalled();
  });

  it("unlinks a beat via the × on its badge", async () => {
    const acts = actions();
    renderWithActions({ beats: [beat({ beat_id: "b1", title: "Call to Adventure" })] }, acts, "card_u1");
    await fireEvent.click(screen.getByRole("button", { name: /Unlink beat Call to Adventure/ }));
    expect(acts.onUnlinkBeat).toHaveBeenCalledWith("card_u1", "i1", "b1");
  });

  it("shows no unlink × on the badges of a read-only card (no actions)", () => {
    render(PlotCardNode, { props: { data: data({ beats: [beat()] }) } });
    expect(screen.queryByRole("button", { name: /Unlink beat/ })).toBeNull();
  });

  it("makes every beat removable on an interactive card, past the read-only +N cap", () => {
    const many = Array.from({ length: 6 }, (_, i) => beat({ beat_id: `b${i}`, title: `Beat ${i}` }));
    const { container } = renderWithActions({ beats: many }, actions(), "card_many");
    // All six carry an × (no beat hidden behind a non-removable +N chip).
    expect(container.querySelectorAll(".beat-badge-x")).toHaveLength(6);
    expect(screen.queryByText(/^\+\d/)).toBeNull();
  });
});
