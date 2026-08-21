// @vitest-environment happy-dom
// The per-project Details-rail layout store (#1246). These lock its contract:
// defaults with nothing stored, a per-project round-trip through localStorage,
// and defensive clamping of corrupt or out-of-range stored dimensions.
import { describe, it, expect, beforeEach } from "vitest";
import {
  editorRailLayout as layout,
  RAIL_WIDTH_DEFAULT,
  RAIL_WIDTH_MAX,
  RAIL_HEIGHT_DEFAULT,
  RAIL_HEIGHT_MIN,
} from "./editorRailLayout.svelte";

const PATH = "C:/proj/book";
const KEY = "lwa.editorRail:" + PATH;

describe("editorRailLayout", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to the right dock at the default size when nothing is stored", () => {
    layout.loadForProject(PATH);
    expect(layout.side).toBe("right");
    expect(layout.width).toBe(RAIL_WIDTH_DEFAULT);
    expect(layout.height).toBe(RAIL_HEIGHT_DEFAULT);
    expect(layout.collapsed).toBe(false);
  });

  it("persists changes per project and reloads them", () => {
    layout.loadForProject(PATH);
    layout.setSide("bottom");
    layout.setHeight(320);
    layout.setCollapsed(true);

    // A fresh load of the same project reads back the stored layout.
    layout.loadForProject("C:/proj/other"); // switch away
    expect(layout.side).toBe("right"); // other project = defaults
    layout.loadForProject(PATH); // switch back
    expect(layout.side).toBe("bottom");
    expect(layout.height).toBe(320);
    expect(layout.collapsed).toBe(true);
  });

  it("writes a single JSON blob under the per-project key", () => {
    layout.loadForProject(PATH);
    layout.setSide("bottom");
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    expect(raw).toMatchObject({ side: "bottom", width: RAIL_WIDTH_DEFAULT });
  });

  it("clamps an out-of-range stored width to the bounds, and a corrupt one to the default", () => {
    localStorage.setItem(KEY, JSON.stringify({ side: "bottom", width: 99999, height: 5 }));
    layout.loadForProject(PATH);
    expect(layout.width).toBe(RAIL_WIDTH_MAX); // over-max clamps down
    expect(layout.height).toBe(RAIL_HEIGHT_MIN); // under-min clamps up

    localStorage.setItem(KEY, JSON.stringify({ width: "wide" }));
    layout.loadForProject(PATH);
    expect(layout.width).toBe(RAIL_WIDTH_DEFAULT); // non-numeric → default
  });

  it("ignores an unknown side value, falling back to right", () => {
    localStorage.setItem(KEY, JSON.stringify({ side: "floating" }));
    layout.loadForProject(PATH);
    expect(layout.side).toBe("right");
  });

  it("does not persist when no project is loaded", () => {
    layout.loadForProject(""); // no project
    layout.setSide("bottom");
    expect(localStorage.getItem("lwa.editorRail:")).toBeNull();
  });
});
