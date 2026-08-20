// Region homing (#757) — where ensureVisible drops a not-yet-placed region. The
// plot board is a large SvelteFlow canvas, so it must home to the CENTRAL editor
// group like the open documents, not the side column. HOMES drives this (and
// doubles as the known-region allowlist), so an accidental removal would silently
// send the board back to the narrow side and stop it persisting.
import { beforeEach, describe, expect, it } from "vitest";
import { workspaceLayout } from "./workspaceLayout.svelte";
import {
  deserialize,
  flattenPanels,
  group,
  G_EDITOR,
  G_SIDE,
  serialize,
  split,
} from "./workspaceLayout.serialize";

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

  it("homes the Plot templates shelf to the side column", () => {
    // A Library shelf like prompts — side column, and a KNOWN region so it
    // survives a reload (#756). Was absent from HOMES, so it docked narrow and
    // was dropped on restore.
    workspaceLayout.ensureVisible("plotTemplates");
    expect(workspaceLayout.groupOf("plotTemplates")?.id).toBe(G_SIDE);
  });
});

// #756: the Plot templates tab is a known region now, so a persisted layout that
// names it must be RESTORED (not dropped like the retired `project` region below).
describe("Plot templates region survives a reload (#756)", () => {
  it("keeps a persisted `plotTemplates` tab on load", () => {
    const saved = JSON.stringify({
      version: 1,
      root: {
        kind: "split",
        id: "s-left",
        dir: "col",
        children: [
          { kind: "group", id: "g-side", tabs: ["plotTemplates"], active: "plotTemplates" },
          { kind: "group", id: "g-draft", tabs: ["outline"], active: "outline" },
        ],
        sizes: [0.4, 0.6],
      },
      activeEditorGroupId: G_EDITOR,
      activePreset: "writing",
    });

    const restored = deserialize(saved);
    expect(restored).not.toBeNull();
    expect(flattenPanels(restored!.root)).toContain("plotTemplates");
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

// #168: the schema_type (field-definitions) editor is a KNOWN region so it homes
// during a session, but its content is transient in-component selection state
// that is persisted nowhere. So it must never round-trip through storage — a
// restored schema_type tab would mount blank with no recovery (a "zombie" pane).
// Both halves of the guard are exercised: stripped on serialize, dropped on load.
describe("schema_type editor is ephemeral, never rehydrated (#168)", () => {
  it("strips a schema_type tab on serialize but keeps its side-column siblings", () => {
    const sideGroup = group(G_SIDE, ["schema", "schema_type"]);
    sideGroup.active = "schema_type";
    const tree = split("root", "row", [group(G_EDITOR, []), sideGroup], [0.6, 0.4]);

    const snapshot = serialize(tree, G_EDITOR, null);
    const tabs = flattenPanels(snapshot.root);
    expect(tabs).not.toContain("schema_type");
    // The store-derived tree tab is self-sufficient and must survive.
    expect(tabs).toContain("schema");
  });

  it("drops a schema_type tab persisted before this fix, on load", () => {
    // A snapshot written by the pre-fix code that still names schema_type.
    const legacy = JSON.stringify({
      version: 1,
      root: {
        kind: "split",
        id: "s-right",
        dir: "col",
        children: [
          { kind: "group", id: G_SIDE, tabs: ["schema", "schema_type"], active: "schema_type" },
          { kind: "group", id: "g-tools", tabs: ["todo"], active: "todo" },
        ],
        sizes: [0.6, 0.4],
      },
      activeEditorGroupId: G_EDITOR,
      activePreset: "writing",
    });

    const restored = deserialize(legacy);
    expect(restored).not.toBeNull();
    const tabs = flattenPanels(restored!.root);
    expect(tabs).not.toContain("schema_type");
    // The rest of the layout is untouched.
    expect(tabs).toContain("schema");
    expect(tabs).toContain("todo");
  });
});

// ADR-0062 D2 (formerly the Preview-only `preview:<editorPaneId>`, S2): a
// detached prompt editor sub-tab (`subtab:<tabId>:<editorPaneId>`) is the same
// zombie shape — a live view of an open editor, reconstructed only while that
// editor is mounted. It must never survive a reload, exactly like schema_type.
describe("detached prompt editor sub-tab is ephemeral, never rehydrated (ADR-0062 D2)", () => {
  it("strips a subtab:<tabId>:<paneId> tab on serialize but keeps its neighbour", () => {
    const subtabGroup = group("g-sub", ["subtab:preview:editor_abc123"]);
    const tree = split(
      "root",
      "row",
      [group(G_EDITOR, ["editor_abc123"]), subtabGroup, group(G_SIDE, ["lore"])],
      [0.4, 0.3, 0.3],
    );

    const snapshot = serialize(tree, G_EDITOR, null);
    const tabs = flattenPanels(snapshot.root);
    expect(tabs).not.toContain("subtab:preview:editor_abc123");
    // Editor docs are ephemeral too; the self-sufficient region survives.
    expect(tabs).toContain("lore");
  });

  it("drops a persisted subtab:<tabId>:<paneId> tab on load", () => {
    const legacy = JSON.stringify({
      version: 1,
      root: {
        kind: "split",
        id: "root",
        dir: "row",
        children: [
          { kind: "group", id: G_EDITOR, tabs: [], active: null },
          { kind: "group", id: "g-sub", tabs: ["subtab:preview:editor_abc123"], active: "subtab:preview:editor_abc123" },
          { kind: "group", id: G_SIDE, tabs: ["lore"], active: "lore" },
        ],
        sizes: [0.4, 0.3, 0.3],
      },
      activeEditorGroupId: G_EDITOR,
      activePreset: "writing",
    });

    const restored = deserialize(legacy);
    expect(restored).not.toBeNull();
    const tabs = flattenPanels(restored!.root);
    expect(tabs).not.toContain("subtab:preview:editor_abc123");
    expect(tabs).toContain("lore");
  });
});
