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

const data = (over: Partial<PlotCardData> = {}): PlotCardData => ({
  title: "She leaves home",
  synopsis: "The heroine packs a bag and walks out.",
  attached: false,
  color: null,
  ...over,
});

function actions(): PlotCardActions {
  return { onOpen: vi.fn(), onRealize: vi.fn(), onDetach: vi.fn(), onEditSynopsis: vi.fn() };
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

  it("shows scene attachment state", () => {
    render(PlotCardNode, { props: { data: data({ attached: true }) } });
    expect(screen.getByText("Scene attached")).toBeInTheDocument();
  });

  it("shows an unattached card as having no scene", () => {
    render(PlotCardNode, { props: { data: data({ attached: false }) } });
    expect(screen.getByText("No scene")).toBeInTheDocument();
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

  it("edits the synopsis in place and commits the change on blur", async () => {
    const acts = actions();
    renderWithActions({ synopsis: "old" }, acts, "card_3");
    await fireEvent.click(screen.getByRole("button", { name: "old" }));
    const box = screen.getByPlaceholderText("Add a synopsis…") as HTMLTextAreaElement;
    await fireEvent.input(box, { target: { value: "new synopsis" } });
    await fireEvent.blur(box);
    expect(acts.onEditSynopsis).toHaveBeenCalledWith("card_3", "new synopsis");
  });
});
