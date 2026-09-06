// Generic post-write reconcile entry point (ADR-0085 §5, slice 3): the
// pane-matching + dirty-guard contract and the per-kind re-baseline, driven
// against a fake host — mirroring editorPanes.navigation.test.ts's host
// mocking and editorPaneSaveFailure.test.ts's "drive the policy in isolation"
// approach, rather than the real singleton controller + a mounted NodeEditor.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isNodeOpenDirty, reconcileNodeFromServer, type PaneReconcileHost } from "./editorPaneReconcile";
import { createEmptyEditorPane, type EditorPaneState } from "@/lib/editor-core/editorPaneModel";
import type { LoreEntry, Scene } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    getScene: vi.fn(),
    getLoreEntry: vi.fn(),
  },
}));
import { api } from "@/lib/api";

function paneFor(document: EditorPaneState["document"], overrides: Partial<EditorPaneState> = {}): EditorPaneState {
  return { ...createEmptyEditorPane("p1"), document, ...overrides };
}

function fakeHost(panes: EditorPaneState[]): PaneReconcileHost & {
  patchPane: ReturnType<typeof vi.fn>;
  reconcileSceneFromServer: ReturnType<typeof vi.fn>;
} {
  const host = {
    panes,
    patchPane: vi.fn((id: string, patch: Partial<EditorPaneState>) => {
      host.panes = host.panes.map((pane) => (pane.id === id ? { ...pane, ...patch } : pane));
    }),
    reconcileSceneFromServer: vi.fn(async () => {}),
    editorPaneComponents: { p1: { reloadScene: vi.fn() } } as PaneReconcileHost["editorPaneComponents"],
  };
  return host;
}

beforeEach(() => {
  vi.mocked(api.getScene).mockReset();
  vi.mocked(api.getLoreEntry).mockReset();
});

describe("isNodeOpenDirty", () => {
  it("is true only for a matching open, dirty pane", () => {
    const pane = paneFor({ type: "lore", id: "lore_1" }, { dirty: true });
    const host = fakeHost([pane]);

    expect(isNodeOpenDirty(host, "lore_1", "lore")).toBe(true);
    expect(isNodeOpenDirty(host, "lore_2", "lore")).toBe(false); // different id, same kind
  });

  it("is false for a clean pane, and for a kind/entry_type with no pane at all", () => {
    const pane = paneFor({ type: "lore", id: "lore_1" }, { dirty: false });
    const host = fakeHost([pane]);

    expect(isNodeOpenDirty(host, "lore_1", "lore")).toBe(false);
    expect(isNodeOpenDirty(host, "arc_1", "plot", "plot:character_arc")).toBe(false);
  });
});

describe("reconcileNodeFromServer", () => {
  it("no-ops when no pane is open for the node", async () => {
    const host = fakeHost([]);

    await reconcileNodeFromServer(host, "scene_1", "manuscript");

    expect(host.reconcileSceneFromServer).not.toHaveBeenCalled();
    expect(api.getScene).not.toHaveBeenCalled();
  });

  it("no-ops for a dirty pane — never discards edits", async () => {
    const pane = paneFor({ type: "manuscript", id: "scene_1" }, { dirty: true });
    const host = fakeHost([pane]);

    await reconcileNodeFromServer(host, "scene_1", "manuscript");

    expect(host.reconcileSceneFromServer).not.toHaveBeenCalled();
    expect(api.getScene).not.toHaveBeenCalled();
  });

  it("no-ops for plot:character_arc — no pane exists for that entry type", async () => {
    const pane = paneFor({ type: "plot_card", id: "arc_1" }, { dirty: false });
    const host = fakeHost([pane]);

    await reconcileNodeFromServer(host, "arc_1", "plot", "plot:character_arc");

    expect(host.patchPane).not.toHaveBeenCalled();
    expect(host.reconcileSceneFromServer).not.toHaveBeenCalled();
  });

  it("reconciles an open, clean scene through reconcileSceneFromServer", async () => {
    const pane = paneFor({ type: "manuscript", id: "scene_1" }, { dirty: false });
    const host = fakeHost([pane]);
    const scene = { id: "scene_1", title: "A", body: "b", status: "draft" } as unknown as Scene;
    vi.mocked(api.getScene).mockResolvedValue(scene);

    await reconcileNodeFromServer(host, "scene_1", "manuscript");

    expect(api.getScene).toHaveBeenCalledWith("scene_1");
    expect(host.reconcileSceneFromServer).toHaveBeenCalledWith(scene, "boundary");
  });

  it("patches a lore pane's baseline from the getter, preserving its authoring layer", async () => {
    const pane = paneFor({ type: "lore", id: "lore_1" }, { dirty: false, authoringLayerId: "layer_a" });
    const host = fakeHost([pane]);
    const entry: LoreEntry = {
      id: "lore_1",
      title: "New title",
      body: "new body",
      revision: "rev2",
      entry_type: "lore:character",
      metadata: {},
      computed_metadata: {},
    };
    vi.mocked(api.getLoreEntry).mockResolvedValue(entry);

    await reconcileNodeFromServer(host, "lore_1", "lore");

    expect(api.getLoreEntry).toHaveBeenCalledWith("lore_1");
    const updated = host.panes.find((candidate) => candidate.id === "p1");
    expect(updated).toMatchObject({
      scene: entry,
      dirty: false,
      draftTitle: "New title",
      draftMarkdown: "new body",
      draftEntryType: "lore:character",
      authoringLayerId: "layer_a", // a replace never moves a layer
    });
    // The body-redraw gap the ADR names: reloadScene IS still called (it
    // forwards to the mounted body view, which redraws for a prose body).
    expect(host.editorPaneComponents.p1?.reloadScene).toHaveBeenCalledWith(entry, "boundary");
  });
});
