// @vitest-environment happy-dom
// ADR-0069 — a view's render layout (mode/density) is ui state paneViews holds
// and persists. Pins the store logic the endpoint tests can't reach: reading
// ui.appearance off the roster summary, the optimistic set + revert-on-failure,
// the clear, and the resolvedViewId keying (selected view vs view_default_<kind>).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { paneViews } from "./paneViews.svelte";
import { api } from "@/lib/api";
import type { ViewNodeSummary } from "@/lib/types";

const KEY = "paneView.selected.lore";
const VIEW_ID = "view_lore_1";

function summary(overrides: Partial<ViewNodeSummary>): ViewNodeSummary {
  return {
    id: VIEW_ID,
    title: "My lore view",
    view_kind: "lore",
    spec: { kind: "lore", expr: { tagged: "x" } },
    ...overrides,
  } as unknown as ViewNodeSummary;
}

beforeEach(() => {
  localStorage.clear();
  paneViews.reset();
  vi.spyOn(api, "listViews").mockResolvedValue({ entries: [] });
});
afterEach(() => {
  localStorage.clear();
  paneViews.reset();
  vi.restoreAllMocks();
});

describe("paneViews — view appearance (ADR-0069)", () => {
  it("reads ui.appearance off the resolved view's roster summary", async () => {
    localStorage.setItem(KEY, VIEW_ID);
    vi.spyOn(api, "listViews").mockResolvedValue({
      entries: [summary({ ui: { collapsed: [], appearance: { mode: "tree", density: "compact" } } })],
    });
    await paneViews.loadForProject("/proj");
    expect(paneViews.appearanceFor("lore")).toEqual({ mode: "tree", density: "compact" });
  });

  it("returns null (⇒ pane default) when the view set no appearance", async () => {
    localStorage.setItem(KEY, VIEW_ID);
    vi.spyOn(api, "listViews").mockResolvedValue({ entries: [summary({ ui: { collapsed: ["node:a"] } })] });
    await paneViews.loadForProject("/proj");
    expect(paneViews.appearanceFor("lore")).toBeNull();
  });

  it("setAppearance updates optimistically and persists only the appearance field", async () => {
    localStorage.setItem(KEY, VIEW_ID);
    vi.spyOn(api, "listViews").mockResolvedValue({ entries: [summary({})] });
    await paneViews.loadForProject("/proj");
    const put = vi.spyOn(api, "updateViewUi").mockResolvedValue({} as never);
    await paneViews.setAppearance("lore", { mode: "card" });
    expect(paneViews.appearanceFor("lore")).toEqual({ mode: "card" });
    expect(put).toHaveBeenCalledWith(VIEW_ID, { appearance: { mode: "card" } });
    // A second patch merges onto the first (mode kept, density added).
    await paneViews.setAppearance("lore", { density: "dense" });
    expect(paneViews.appearanceFor("lore")).toEqual({ mode: "card", density: "dense" });
  });

  it("setAppearance reverts the optimistic value when the write fails", async () => {
    localStorage.setItem(KEY, VIEW_ID);
    await paneViews.loadForProject("/proj");
    vi.spyOn(api, "updateViewUi").mockRejectedValue(new Error("offline"));
    await paneViews.setAppearance("lore", { mode: "tree" });
    // Reverted to "no appearance" (there was none before), so the pane default holds.
    expect(paneViews.appearanceFor("lore")).toBeNull();
  });

  it("clearAppearance drops the layout and sends appearance: null", async () => {
    localStorage.setItem(KEY, VIEW_ID);
    vi.spyOn(api, "listViews").mockResolvedValue({ entries: [summary({})] });
    await paneViews.loadForProject("/proj");
    const put = vi.spyOn(api, "updateViewUi").mockResolvedValue({} as never);
    await paneViews.setAppearance("lore", { mode: "card" });
    await paneViews.clearAppearance("lore");
    expect(paneViews.appearanceFor("lore")).toBeNull();
    expect(put).toHaveBeenLastCalledWith(VIEW_ID, { appearance: null });
  });

  it("keys appearance by the resolved view id — the default kind when unselected", async () => {
    // No selection ⇒ resolvedViewId is view_default_lore; a write persists against it.
    await paneViews.loadForProject("/proj");
    const put = vi.spyOn(api, "updateViewUi").mockResolvedValue({} as never);
    await paneViews.setAppearance("lore", { density: "compact" });
    expect(put).toHaveBeenCalledWith("view_default_lore", { appearance: { density: "compact" } });
    expect(paneViews.appearanceFor("lore")).toEqual({ density: "compact" });
  });
});
