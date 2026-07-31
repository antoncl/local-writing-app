// Region homing (#757) — where ensureVisible drops a not-yet-placed region. The
// plot board is a large SvelteFlow canvas, so it must home to the CENTRAL editor
// group like the open documents, not the side column. HOMES drives this (and
// doubles as the known-region allowlist), so an accidental removal would silently
// send the board back to the narrow side and stop it persisting.
import { beforeEach, describe, expect, it } from "vitest";
import { workspaceLayout } from "./workspaceLayout.svelte";
import { deserialize, flattenPanels, G_EDITOR, G_SIDE } from "./workspaceLayout.serialize";

describe("workspaceLayout region homing (#757)", () => {
  beforeEach(() => workspaceLayout.reset());

  it("homes the plot board to the central editor group", () => {
    workspaceLayout.ensureVisible("plotEditor");
    expect(workspaceLayout.groupOf("plotEditor")?.id).toBe(G_EDITOR);
  });

  it("still homes a side region (lore) to the side column", () => {
    workspaceLayout.ensureVisible("lore");
    expect(workspaceLayout.groupOf("lore")?.id).toBe(G_SIDE);
  });
});

// The Project pane was deleted (#417 slice 6), so `project` is no longer a known
// region. A per-project layout snapshot persisted before the deletion still
// names it; deserialize must drop the now-unknown tab (isKnownTab) and prune the
// group it emptied, rather than resurrect a dead region or reject the tree.
describe("retired `project` region degrades gracefully (#417 slice 6)", () => {
  it("drops a persisted `project` tab on load and keeps the rest of the tree", () => {
    // The old default: Project stacked over Draft in the left column.
    const legacy = JSON.stringify({
      version: 1,
      root: {
        kind: "split",
        id: "s-left",
        dir: "col",
        children: [
          { kind: "group", id: "g-project", tabs: ["project"], active: "project" },
          { kind: "group", id: "g-draft", tabs: ["outline"], active: "outline" },
        ],
        sizes: [0.4, 0.6],
      },
      activeEditorGroupId: G_EDITOR,
      activePreset: "writing",
    });

    const restored = deserialize(legacy);
    expect(restored).not.toBeNull();
    const tabs = flattenPanels(restored!.root);
    expect(tabs).not.toContain("project");
    expect(tabs).toContain("outline");
  });
});
