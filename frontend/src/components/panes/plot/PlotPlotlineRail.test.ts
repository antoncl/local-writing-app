// @vitest-environment happy-dom
// PlotPlotlineRail RENDER guard (#737). The plotlines rail DISPLAYS the book's
// plotlines (name, card count, swatch dot = the board's colour legend), so it needs
// a mount test asserting the content renders and the actions fire
// ([[reference_component_test_harness]]). Plain sidebar, no @xyflow/svelte import.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotPlotlineRail from "./PlotPlotlineRail.svelte";
import { setPalette } from "@/lib/utils/colors";
import type { PlotlineSummary } from "@/lib/types";

const plotline = (over: Partial<PlotlineSummary> & { id: string; title: string }): PlotlineSummary => ({
  body: "",
  entry_type: "plot:plotline",
  metadata: {},
  ...over,
});

function renderRail(over: { plotlines?: PlotlineSummary[]; cardCounts?: Record<string, number> } = {}) {
  const props = {
    plotlines: [] as PlotlineSummary[],
    cardCounts: {} as Record<string, number>,
    onCreate: vi.fn(),
    onOpen: vi.fn(),
    onRemove: vi.fn(),
    ...over,
  };
  render(PlotPlotlineRail, { props });
  return props;
}

afterEach(() => setPalette([]));

describe("PlotPlotlineRail (#737)", () => {
  it("shows an empty-state hint when there are no plotlines", () => {
    renderRail();
    expect(screen.getByText(/no plotlines yet/i)).toBeInTheDocument();
  });

  it("lists each plotline with its name and card count", () => {
    renderRail({
      plotlines: [plotline({ id: "pl_a", title: "Redemption" }), plotline({ id: "pl_b", title: "The conspiracy" })],
      cardCounts: { pl_a: 3 },
    });
    expect(screen.getByRole("button", { name: "Redemption" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "The conspiracy" })).toBeInTheDocument();
    // pl_a has 3 cards → a count pill; pl_b has none → no pill.
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("resolves a plotline's swatch to a coloured dot, hollow when colourless", () => {
    setPalette([{ id: "forest", label: "Forest", hex: "#3f7d68" }]);
    renderRail({
      plotlines: [
        plotline({ id: "pl_a", title: "Coloured", metadata: { color: "forest" } }),
        plotline({ id: "pl_b", title: "Colourless" }),
      ],
    });
    const dots = document.querySelectorAll(".pl-dot");
    expect(dots).toHaveLength(2);
    expect((dots[0] as HTMLElement).style.cssText).toContain("#3f7d68");
    expect(dots[1].classList.contains("hollow")).toBe(true);
  });

  it("fires onCreate / onOpen / onRemove for the writer's gestures", async () => {
    const props = renderRail({ plotlines: [plotline({ id: "pl_a", title: "Redemption" })] });
    await fireEvent.click(screen.getByRole("button", { name: "New plotline" }));
    expect(props.onCreate).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole("button", { name: "Redemption" }));
    expect(props.onOpen).toHaveBeenCalledWith("pl_a");
    await fireEvent.click(screen.getByRole("button", { name: "Remove this plotline" }));
    expect(props.onRemove).toHaveBeenCalledWith("pl_a");
  });
});
