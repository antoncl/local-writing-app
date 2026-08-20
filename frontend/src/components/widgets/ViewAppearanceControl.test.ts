// @vitest-environment happy-dom
// #1196: the Layout control's mode/density groups are mutually-exclusive
// toggles, so before the user picks anything the effective DEFAULT must read as
// selected — never a blank toggle. The default is resolved from the same single
// source the pane renders through (paneViews.defaultModeFor), so the control
// can't show a mode the pane doesn't actually render.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { api } from "@/lib/api";
import ViewAppearanceControl from "./ViewAppearanceControl.svelte";

beforeEach(() => {
  localStorage.clear();
  paneViews.reset();
});
afterEach(() => {
  localStorage.clear();
  paneViews.reset();
  vi.restoreAllMocks();
});

async function openLayout() {
  await fireEvent.click(screen.getByRole("button", { name: "View layout" }));
}

describe("ViewAppearanceControl — effective default is selected (#1196)", () => {
  it("a card-list pane shows Cards + Comfortable selected with no stored appearance", async () => {
    render(ViewAppearanceControl, { props: { kind: "lore" } });
    await openLayout();
    expect(screen.getByRole("menuitemradio", { name: "Cards" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Tree" })).not.toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Comfortable" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Compact" })).not.toBeChecked();
  });

  it("the manuscript outline (a tree pane) shows Tree selected, not Cards", async () => {
    render(ViewAppearanceControl, { props: { kind: "manuscript" } });
    await openLayout();
    expect(screen.getByRole("menuitemradio", { name: "Tree" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Cards" })).not.toBeChecked();
  });

  it("a stored appearance overrides the default selection", async () => {
    vi.spyOn(api, "updateViewUi").mockResolvedValue({} as never);
    render(ViewAppearanceControl, { props: { kind: "lore" } });
    // A card pane whose view stored mode:tree should show Tree, not the default.
    await paneViews.setAppearance("lore", { mode: "tree" });
    await openLayout();
    expect(screen.getByRole("menuitemradio", { name: "Tree" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Cards" })).not.toBeChecked();
  });
});
