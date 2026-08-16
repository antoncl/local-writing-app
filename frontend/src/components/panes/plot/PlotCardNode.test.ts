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
import { setPalette } from "@/lib/utils/colors";

const beat = (over: Partial<PlotBoardBeat> = {}): PlotBoardBeat => ({
  plotline_id: "i1",
  plotline_title: "Hero's Journey",
  plotline_color: null,
  beat_id: "b1",
  title: "Call to Adventure",
  number: 1,
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

function actions(
  plotlines: PlotCardActions["plotlines"] = [],
  focusedPlotlineId: string | null = null,
  locations: PlotCardActions["locations"] = [],
  highlightedCardIds: ReadonlySet<string> | null = null,
): PlotCardActions {
  return {
    onOpen: vi.fn(),
    onRealize: vi.fn(),
    onDetach: vi.fn(),
    onEditTitle: vi.fn(),
    onEditSynopsis: vi.fn(),
    onSetPlotline: vi.fn(),
    onLinkBeat: vi.fn(),
    onUnlinkBeat: vi.fn(),
    onMoveBeat: vi.fn(),
    onSetPageStatus: vi.fn(),
    onDelete: vi.fn(),
    onMenuOpenChange: vi.fn(),
    plotlines,
    focusedPlotlineId,
    locations,
    highlightedCardIds,
  };
}

// A stand-in DataTransfer carrying a beat drag. `from` (a source card id) marks a
// badge drag moving card→card (#941); omitted, it's a plotline-node link drag (#824).
function beatDataTransfer(plotline: string, beatId: string, from?: string): DataTransfer {
  const payload = from ? { kind: "beat", plotline, beat_id: beatId, from } : { kind: "beat", plotline, beat_id: beatId };
  const store: Record<string, string> = { [PLOT_DND_MIME]: JSON.stringify(payload) };
  return {
    types: Object.keys(store),
    getData: (t: string) => store[t] ?? "",
    setData: (t: string, v: string) => void (store[t] = v),
    dropEffect: "none",
    effectAllowed: from ? "move" : "all",
  } as unknown as DataTransfer;
}

// A stand-in DataTransfer that records setData calls — for asserting what a badge's
// dragstart writes into the drag channel.
function recordingDataTransfer(): { dt: DataTransfer; store: Record<string, string> } {
  const store: Record<string, string> = {};
  const dt = {
    setData: (t: string, v: string) => void (store[t] = v),
    getData: (t: string) => store[t] ?? "",
    types: [] as string[],
    dropEffect: "none",
    effectAllowed: "none",
  } as unknown as DataTransfer;
  return { dt, store };
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

  // The drag handle (#876): an interactive board grips the card by a leading handle
  // (SvelteFlow's dragHandle targets it), so its control-dense body stays edit-only.
  it("renders the drag-handle grip on an interactive card, and omits it read-only (#876)", () => {
    const { container, unmount } = renderWithActions({}, actions());
    const grip = container.querySelector(".plot-card-drag-handle");
    expect(grip).not.toBeNull();
    // The app's standard grip icon (a generous, hittable handle — not a collapsing glyph).
    expect(grip!.querySelector("i.ti-grip-vertical")).not.toBeNull();
    unmount();
    // No actions (read-only mount / non-interactive board) → nothing to drag, no grip.
    const { container: ro } = render(PlotCardNode, { props: { data: data() } });
    expect(ro.querySelector(".plot-card-drag-handle")).toBeNull();
  });
});

describe("PlotCardNode — per-plotline focus (ADR-0053 §6, S5b; #911 lit outline + dim)", () => {
  const cardEl = (c: HTMLElement) => c.querySelector(".plot-card")!;

  it("neither lits nor dims any card when nothing is focused", () => {
    const { container } = renderWithActions({ plotlineId: "Q" }, actions([], null));
    expect(cardEl(container).classList.contains("dimmed")).toBe(false);
    expect(cardEl(container).classList.contains("lit")).toBe(false);
  });

  it("dims (not lits) a card that is neither on the focused thread nor fulfilling its beats", () => {
    // Focus P; this card is on Q and only fulfils an R beat → it recedes.
    const { container } = renderWithActions(
      { plotlineId: "Q", beats: [beat({ plotline_id: "R" })] },
      actions([], "P"),
    );
    expect(cardEl(container).classList.contains("dimmed")).toBe(true);
    expect(cardEl(container).classList.contains("lit")).toBe(false);
  });

  it("LITS (not dims) a card whose PRIMARY plotline is the focused one", () => {
    const { container } = renderWithActions({ plotlineId: "P" }, actions([], "P"));
    expect(cardEl(container).classList.contains("lit")).toBe(true);
    expect(cardEl(container).classList.contains("dimmed")).toBe(false);
  });

  it("LITS a card that fulfils one of the focused plotline's beats, even off its primary", () => {
    const { container } = renderWithActions(
      { plotlineId: "Q", beats: [beat({ plotline_id: "P", beat_id: "b7" })] },
      actions([], "P"),
    );
    expect(cardEl(container).classList.contains("lit")).toBe(true);
    expect(cardEl(container).classList.contains("dimmed")).toBe(false);
  });

  it("neither lits nor dims without an actions context (read-only board)", () => {
    const { container } = render(PlotCardNode, { props: { data: data({ plotlineId: "Q" }) } });
    expect(cardEl(container).classList.contains("dimmed")).toBe(false);
    expect(cardEl(container).classList.contains("lit")).toBe(false);
  });
});

describe("PlotCardNode — diagnostic highlight (ADR-0048 S7 lit set)", () => {
  const cardEl = (c: HTMLElement) => c.querySelector(".plot-card")!;

  it("LITS a card whose id is in the highlighted set", () => {
    const { container } = renderWithActions({}, actions([], null, [], new Set(["card_1"])), "card_1");
    expect(cardEl(container).classList.contains("lit")).toBe(true);
    expect(cardEl(container).classList.contains("dimmed")).toBe(false);
  });

  it("DIMS a card outside the highlighted set", () => {
    const { container } = renderWithActions({}, actions([], null, [], new Set(["other"])), "card_1");
    expect(cardEl(container).classList.contains("dimmed")).toBe(true);
    expect(cardEl(container).classList.contains("lit")).toBe(false);
  });

  it("takes precedence over plotline focus (a finding is selected AND a thread was focused)", () => {
    // On thread P (would be lit by focus) but outside the highlight set → the finding wins → dimmed.
    const { container } = renderWithActions(
      { plotlineId: "P" },
      actions([], "P", [], new Set(["other"])),
      "card_1",
    );
    expect(cardEl(container).classList.contains("dimmed")).toBe(true);
    expect(cardEl(container).classList.contains("lit")).toBe(false);
  });

  it("an empty highlight set falls back to plotline focus", () => {
    const { container } = renderWithActions({ plotlineId: "P" }, actions([], "P", [], new Set()), "card_1");
    expect(cardEl(container).classList.contains("lit")).toBe(true);
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

  it("realizes with the backend default (null parent) when there are no containers to offer (#879)", async () => {
    const acts = actions(); // no locations → "Realize scene" fires directly
    renderWithActions({ attached: false }, acts, "card_9");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Realize scene" }));
    expect(acts.onRealize).toHaveBeenCalledWith("card_9", null);
  });

  it("realizes into a chosen manuscript location from the submenu (#879)", async () => {
    const acts = actions([], null, [
      { id: "act_1", title: "Act One", depth: 0 },
      { id: "ch_2", title: "Chapter Two", depth: 1 },
    ]);
    renderWithActions({ attached: false }, acts, "card_r");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    // With containers present, "Realize scene" opens a location submenu rather than
    // firing straight away (mirrors "Set plotline").
    await fireEvent.click(screen.getByRole("menuitem", { name: "Realize scene" }));
    expect(acts.onRealize).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Chapter Two" }));
    expect(acts.onRealize).toHaveBeenCalledWith("card_r", "ch_2");
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
      { id: "pl_a", title: "Main plot", color: null, beats: [] },
      { id: "pl_b", title: "Romance", color: null, beats: [] },
    ]);
    renderWithActions({ attached: false }, acts, "card_4");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    // Second page lists the lanes + Unassigned.
    await fireEvent.click(screen.getByRole("menuitem", { name: "Romance" }));
    expect(acts.onSetPlotline).toHaveBeenCalledWith("card_4", "pl_b");
  });

  it("clears the plotline via Unassigned", async () => {
    const acts = actions([{ id: "pl_a", title: "Main plot", color: null, beats: [] }]);
    renderWithActions({ attached: false }, acts, "card_5");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Unassigned" }));
    expect(acts.onSetPlotline).toHaveBeenCalledWith("card_5", "");
  });

  it("marks the card's current plotline in the submenu (#863)", async () => {
    const acts = actions([
      { id: "pl_a", title: "Main plot", color: null, beats: [] },
      { id: "pl_b", title: "Romance", color: null, beats: [] },
    ]);
    renderWithActions({ attached: false, plotlineId: "pl_b", plotlineName: "Romance" }, acts, "card_6");
    await fireEvent.click(screen.getByLabelText("Card actions"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Set plotline" }));
    expect(screen.getByRole("menuitem", { name: "Romance", current: true })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Main plot" })).not.toHaveAttribute("aria-current", "true");
  });

  it("marks Unassigned as current when the card has no plotline (#863)", async () => {
    const acts = actions([{ id: "pl_a", title: "Main plot", color: null, beats: [] }]);
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

  it("shows the beat's roster number on its badge (#941)", () => {
    const { container } = render(PlotCardNode, {
      props: { data: data({ beats: [beat({ title: "Midpoint", number: 5 })] }) },
    });
    const num = container.querySelector(".beat-badge-num");
    expect(num?.textContent).toBe("5");
  });

  it("puts the number AFTER the title and a drag grip BEFORE it on an interactive badge (#941 follow-up)", () => {
    const { container, unmount } = renderWithActions({ beats: [beat({ title: "Midpoint", number: 5 })] }, actions());
    const badge = container.querySelector(".beat-badge")!;
    const classesInOrder = [...badge.children].map((c) => c.className.toString().split(" ")[0]);
    // grip leads, title, then the trailing number (the × follows).
    expect(classesInOrder.slice(0, 3)).toEqual(["beat-badge-grip", "beat-badge-label", "beat-badge-num"]);
    expect(badge.querySelector(".beat-badge-grip i.ti-grip-vertical")).not.toBeNull();
    unmount();
    // Read-only badge: no grip (not draggable), number still shown.
    const { container: ro } = render(PlotCardNode, { props: { data: data({ beats: [beat({ number: 5 })] }) } });
    expect(ro.querySelector(".beat-badge-grip")).toBeNull();
    expect(ro.querySelector(".beat-badge-num")?.textContent).toBe("5");
  });

  it("caps the badges and shows a +N overflow chip instead of hiding beats silently", () => {
    const many = Array.from({ length: 6 }, (_, i) => beat({ beat_id: `b${i}`, title: `Beat ${i}` }));
    render(PlotCardNode, { props: { data: data({ beats: many }) } });
    expect(screen.getByText("Beat 0")).toBeInTheDocument();
    expect(screen.getByText("Beat 3")).toBeInTheDocument(); // first 4 shown
    expect(screen.queryByText("Beat 4")).toBeNull(); // capped
    expect(screen.getByText("+2")).toBeInTheDocument(); // the overflow is visible
  });

  it("tints a beat badge by its arc's colour and leaves a colourless arc neutral", () => {
    setPalette([{ id: "rose", label: "Rose", hex: "#b0567a" }]);
    const { container } = render(PlotCardNode, {
      props: {
        data: data({
          beats: [
            beat({ beat_id: "b1", title: "Call to Adventure", plotline_color: "rose" }),
            beat({ beat_id: "b2", title: "Refusal", plotline_color: null }),
          ],
        }),
      },
    });
    const badges = container.querySelectorAll(".beat-badge");
    expect(badges[0].classList.contains("coloured")).toBe(true);
    expect((badges[0] as HTMLElement).style.getPropertyValue("--beat-accent")).toBe("#b0567a");
    expect(badges[1].classList.contains("coloured")).toBe(false);
  });

  it("falls back to a neutral badge when the arc's swatch is no longer in the palette", () => {
    // A swatch the writer deleted after colouring the arc: getSwatch returns null,
    // so the badge degrades to neutral rather than throwing or emitting an accent.
    setPalette([{ id: "rose", label: "Rose", hex: "#b0567a" }]);
    const { container } = render(PlotCardNode, {
      props: { data: data({ beats: [beat({ beat_id: "b1", title: "Setup", plotline_color: "ghost" })] }) },
    });
    const badge = container.querySelector(".beat-badge") as HTMLElement;
    expect(badge.classList.contains("coloured")).toBe(false);
    expect(badge.style.getPropertyValue("--beat-accent")).toBe("");
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

  it("MOVES a beat here when a badge dragged from another card is dropped (#941)", async () => {
    const acts = actions();
    const { container } = renderWithActions({ beats: [] }, acts, "card_to");
    const card = container.querySelector(".plot-card") as HTMLElement;
    const dataTransfer = beatDataTransfer("i1", "b1", "card_from");
    await fireEvent.dragOver(card, { dataTransfer });
    await fireEvent.drop(card, { dataTransfer });
    expect(acts.onMoveBeat).toHaveBeenCalledWith("card_from", "card_to", "i1", "b1");
    expect(acts.onLinkBeat).not.toHaveBeenCalled();
  });

  it("LINKS (does not move) a badge dropped back on its own card (#941)", async () => {
    const acts = actions();
    const { container } = renderWithActions({ beats: [beat()] }, acts, "card_self");
    const card = container.querySelector(".plot-card") as HTMLElement;
    const dataTransfer = beatDataTransfer("i1", "b1", "card_self"); // from === this card
    await fireEvent.drop(card, { dataTransfer });
    expect(acts.onMoveBeat).not.toHaveBeenCalled();
    expect(acts.onLinkBeat).toHaveBeenCalledWith("card_self", "i1", "b1");
  });

  it("a badge drag carries its source card id so the drop can move it (#941)", async () => {
    const acts = actions();
    const { container } = renderWithActions({ beats: [beat({ beat_id: "b9" })] }, acts, "card_src");
    const badge = container.querySelector(".beat-badge") as HTMLElement;
    const { dt, store } = recordingDataTransfer();
    await fireEvent.dragStart(badge, { dataTransfer: dt });
    expect(JSON.parse(store[PLOT_DND_MIME])).toMatchObject({
      kind: "beat",
      plotline: "i1",
      beat_id: "b9",
      from: "card_src",
    });
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
