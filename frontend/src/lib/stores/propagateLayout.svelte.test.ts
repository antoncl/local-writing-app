// @vitest-environment happy-dom
// The Propagate pane's persisted divider (ADR-0091 §7) — copy of
// editorRailLayout's own test shape: defaults with nothing stored, a
// per-project round-trip through localStorage, defensive clamping.
import { describe, it, expect, beforeEach } from "vitest";
import {
  propagateLayout as layout,
  PROPAGATE_LIST_WIDTH_DEFAULT,
  PROPAGATE_LIST_WIDTH_MAX,
  PROPAGATE_LIST_WIDTH_MIN,
} from "./propagateLayout.svelte";

const PATH = "C:/proj/book";
const KEY = "lwa.propagateSplit:" + PATH;

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
