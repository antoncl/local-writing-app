// @vitest-environment happy-dom
// #2313: the workspace tab row makes its overflow reachable — ‹ › arrows on the
// side(s) with hidden tabs, and a count button whose menu lists every tab.
// happy-dom has no layout, so the scroll geometry is stubbed per test.
import { afterEach, describe, expect, it, vi } from "vitest";
import { createRawSnippet, tick } from "svelte";
import { fireEvent, render, screen } from "@/lib/test/component";
import WorkspaceTabStrip from "./WorkspaceTabStrip.svelte";
import type { PanelId } from "@/lib/types";

const TABS = ["editor_1", "editor_2", "editor_3"] as PanelId[];
const TITLES: Record<string, string> = { editor_1: "Lysandra", editor_2: "Three Roads", editor_3: "The Hook" };

// Scroll geometry of `.ws-tabs`, applied to every HTMLElement while a test runs.
function stubGeometry(g: { scrollWidth: number; clientWidth: number; scrollLeft: number }) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(g.scrollWidth);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(g.clientWidth);
  vi.spyOn(HTMLElement.prototype, "scrollLeft", "get").mockReturnValue(g.scrollLeft);
}

function renderStrip(active: PanelId = TABS[0]) {
  const onActivate = vi.fn();
  const onClose = vi.fn();
  const tab = createRawSnippet((id: () => PanelId) => ({
    render: () => `<div role="tab">${TITLES[id()]}</div>`,
  }));
  render(WorkspaceTabStrip, {
    props: {
      tabs: TABS,
      active,
      titleOf: (id: PanelId) => TITLES[id],
      closableOf: () => true,
      onActivate,
      onClose,
      tab,
    },
  });
  return { onActivate, onClose };
}

afterEach(() => vi.restoreAllMocks());

describe("WorkspaceTabStrip (#2313)", () => {
  it("renders every tab and no overflow chrome when the tabs fit", async () => {
    stubGeometry({ scrollWidth: 300, clientWidth: 300, scrollLeft: 0 });
    renderStrip();
    await tick();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Scroll tabs/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /All open tabs/ })).toBeNull();
  });

  it("shows only the right arrow at the start of an overflowing row", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    renderStrip();
    await tick();
    expect(screen.getByRole("button", { name: "Scroll tabs right" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scroll tabs left" })).toBeNull();
  });

  it("shows both arrows mid-row", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 300 });
    renderStrip();
    await tick();
    expect(screen.getByRole("button", { name: "Scroll tabs left" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scroll tabs right" })).toBeInTheDocument();
  });

  it("the count menu lists every tab, marks the current one, and switches on pick", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    const { onActivate } = renderStrip(TABS[1]);
    await tick();
    const button = screen.getByRole("button", { name: "All open tabs (3)" });
    expect(button).toHaveTextContent("3");
    await fireEvent.click(button);
    await tick();
    const items = screen.getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Lysandra", "Three Roads", "The Hook"]);
    expect(items[1]).toHaveAttribute("aria-current", "page");
    await fireEvent.click(items[2]);
    expect(onActivate).toHaveBeenCalledWith("editor_3");
  });

  it("the menu's × closes that tab", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    const { onClose, onActivate } = renderStrip();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "All open tabs (3)" }));
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "Close The Hook" }));
    expect(onClose).toHaveBeenCalledWith("editor_3");
    expect(onActivate).not.toHaveBeenCalled();
  });
});
