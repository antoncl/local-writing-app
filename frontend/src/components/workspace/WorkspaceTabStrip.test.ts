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
  const { rerender } = render(WorkspaceTabStrip, {
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
  return { onActivate, onClose, rerender };
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

  // Real scroll geometry on the row element itself, with a writable scrollLeft.
  function rowWithGeometry(g: { scrollWidth: number; clientWidth: number; scrollLeft: number }) {
    const el = document.querySelector(".ws-tabs") as HTMLElement;
    let left = g.scrollLeft;
    Object.defineProperty(el, "scrollWidth", { configurable: true, get: () => g.scrollWidth });
    Object.defineProperty(el, "clientWidth", { configurable: true, get: () => g.clientWidth });
    Object.defineProperty(el, "scrollLeft", { configurable: true, get: () => left, set: (v: number) => (left = v) });
    return el;
  }

  it("a vertical wheel scrolls the row sideways", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    renderStrip();
    await tick();
    const el = rowWithGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 100 });
    const event = new WheelEvent("wheel", { deltaY: 120, cancelable: true });
    el.dispatchEvent(event);
    expect(el.scrollLeft).toBe(220);
    expect(event.defaultPrevented).toBe(true);
  });

  it("reveals the active tab clear of the edge arrow, so its × isn't covered", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    const { rerender } = renderStrip(TABS[0]);
    await tick();
    const el = rowWithGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    const slot = el.querySelector('[data-tab-id="editor_2"]') as HTMLElement;
    Object.defineProperty(slot, "offsetLeft", { configurable: true, get: () => 400 });
    Object.defineProperty(slot, "offsetWidth", { configurable: true, get: () => 100 });
    await rerender({ active: TABS[1] });
    await tick();
    await tick();
    // Right edge 500 + 24px arrow clearance - 300 visible = 224, not the flush 200.
    expect(el.scrollLeft).toBe(224);
  });

  it("the menu does not reopen by itself after the row stops overflowing", async () => {
    const geometry = { scrollWidth: 900, clientWidth: 300, scrollLeft: 0 };
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(() => geometry.scrollWidth);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => geometry.clientWidth);
    vi.spyOn(HTMLElement.prototype, "scrollLeft", "get").mockImplementation(() => geometry.scrollLeft);
    renderStrip();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "All open tabs (3)" }));
    await tick();
    const row = document.querySelector(".ws-tabs") as HTMLElement;
    geometry.scrollWidth = 300; // tabs closed until the row fits
    await fireEvent.scroll(row);
    await tick();
    expect(screen.queryByRole("menu")).toBeNull();
    geometry.scrollWidth = 900; // overflowing again
    await fireEvent.scroll(row);
    await tick();
    expect(screen.getByRole("button", { name: "All open tabs (3)" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("the menu's × leads each row, before the tab name (#2324)", async () => {
    stubGeometry({ scrollWidth: 900, clientWidth: 300, scrollLeft: 0 });
    renderStrip();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "All open tabs (3)" }));
    await tick();
    const close = screen.getByRole("button", { name: "Close The Hook" });
    const item = screen.getByRole("menuitem", { name: "The Hook" });
    expect(close.parentElement).toBe(item.parentElement);
    expect(close.compareDocumentPosition(item) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
