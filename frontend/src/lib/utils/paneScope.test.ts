// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { paneOwnsKey } from "@/lib/utils/paneScope";

// Build a mounted `.editor-panel` (optionally inside a hidden tab) holding a
// handler root, mirroring the workspace DOM (WorkspaceNode's `.hidden-doc` +
// `.editor-panel`).
function pane(hiddenTab = false): { root: HTMLElement; panel: HTMLElement } {
  const tab = document.createElement("div");
  if (hiddenTab) tab.className = "hidden-doc";
  const panel = document.createElement("div");
  panel.className = "editor-panel";
  const root = document.createElement("div");
  panel.appendChild(root);
  tab.appendChild(panel);
  document.body.appendChild(tab);
  return { root, panel };
}

describe("paneOwnsKey", () => {
  it("is false before the root mounts", () => {
    expect(paneOwnsKey(null, null)).toBe(false);
  });

  it("is false for a root inside a hidden tab", () => {
    const { root } = pane(true);
    expect(paneOwnsKey(root, null)).toBe(false);
  });

  it("owns the key when focus is nowhere in an editor pane", () => {
    const { root } = pane();
    expect(paneOwnsKey(root, null)).toBe(true);
    const loose = document.createElement("button"); // not inside any .editor-panel
    document.body.appendChild(loose);
    expect(paneOwnsKey(root, loose)).toBe(true);
  });

  it("owns the key when focus is inside its own pane", () => {
    const { root, panel } = pane();
    const inside = document.createElement("input");
    panel.appendChild(inside);
    expect(paneOwnsKey(root, inside)).toBe(true);
  });

  it("does not own the key when focus is in another editor pane", () => {
    const { root } = pane();
    const other = pane();
    const inOther = document.createElement("input");
    other.panel.appendChild(inOther);
    expect(paneOwnsKey(root, inOther)).toBe(false);
  });
});
