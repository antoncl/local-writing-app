// @vitest-environment happy-dom
// The Propagate pane's persisted divider (ADR-0091 §7) — copy of
// editorRailLayout's own test shape: defaults with nothing stored, a
// per-project round-trip through localStorage, defensive clamping.
import { describe, it, expect, beforeEach } from "vitest";
import {
  clampListWidth,
  propagateLayout as layout,
  PROPAGATE_DIFF_COLUMN_MIN,
  PROPAGATE_LIST_WIDTH_DEFAULT,
  PROPAGATE_LIST_WIDTH_MAX,
  PROPAGATE_LIST_WIDTH_MIN,
} from "./propagateLayout.svelte";

const PATH = "C:/proj/book";
const KEY = "lwa.propagateSplit:" + PATH;

describe("clampListWidth (the drag's clamp, ADR-0091 §7)", () => {
  it("holds the fixed bounds in a wide pane", () => {
    expect(clampListWidth(100, 1200)).toBe(PROPAGATE_LIST_WIDTH_MIN);
    expect(clampListWidth(900, 1200)).toBe(PROPAGATE_LIST_WIDTH_MAX);
    expect(clampListWidth(333.4, 1200)).toBe(333);
  });

  it("caps the list so the diff column keeps its floor in a narrow pane", () => {
    const pane = 450;
    expect(clampListWidth(400, pane)).toBe(pane - PROPAGATE_DIFF_COLUMN_MIN);
  });

  it("never goes below the minimum even in a pane too narrow for the floor", () => {
    expect(clampListWidth(400, 300)).toBe(PROPAGATE_LIST_WIDTH_MIN);
  });
});

describe("propagateLayout", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to the shipped split's list width when nothing is stored", () => {
    layout.loadForProject(PATH);
    expect(layout.listWidth).toBe(PROPAGATE_LIST_WIDTH_DEFAULT);
  });

  it("persists changes per project and reloads them", () => {
    layout.loadForProject(PATH);
    layout.setListWidth(400);

    layout.loadForProject("C:/proj/other"); // switch away
    expect(layout.listWidth).toBe(PROPAGATE_LIST_WIDTH_DEFAULT); // other project = default
    layout.loadForProject(PATH); // switch back
    expect(layout.listWidth).toBe(400);
  });

  it("writes a single JSON blob under the per-project key", () => {
    layout.loadForProject(PATH);
    layout.setListWidth(350);
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    expect(raw).toEqual({ listWidth: 350 });
  });

  it("clamps an out-of-range stored width to the bounds, and a corrupt one to the default", () => {
    localStorage.setItem(KEY, JSON.stringify({ listWidth: 99999 }));
    layout.loadForProject(PATH);
    expect(layout.listWidth).toBe(PROPAGATE_LIST_WIDTH_MAX);

    localStorage.setItem(KEY, JSON.stringify({ listWidth: 5 }));
    layout.loadForProject(PATH);
    expect(layout.listWidth).toBe(PROPAGATE_LIST_WIDTH_MIN);

    localStorage.setItem(KEY, JSON.stringify({ listWidth: "wide" }));
    layout.loadForProject(PATH);
    expect(layout.listWidth).toBe(PROPAGATE_LIST_WIDTH_DEFAULT);
  });

  it("does not persist when no project is loaded", () => {
    layout.loadForProject(""); // no project
    layout.setListWidth(400);
    expect(localStorage.getItem("lwa.propagateSplit:")).toBeNull();
  });
});
