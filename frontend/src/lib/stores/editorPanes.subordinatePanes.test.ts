import { beforeEach, describe, expect, it, vi } from "vitest";

import { editorPanes } from "./editorPanes.svelte";
import { subordinatePanes } from "./subordinatePanes";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument } from "@/lib/types";

// The subordinate-pane cascade at the editorPanes seam — the half the registry's
// own unit test can't see. Two invariants: tearing down a master pane closes its
// registered children, and a project switch (reset) drops every link so a
// surviving one can't mis-fire once the editor-pane id counter restarts.

function scenePane(id: string): void {
  const pane = createEmptyEditorPane(id);
  pane.document = { type: "manuscript", id: `${id}-doc` } as DocumentRef;
  pane.scene = { id: `${id}-doc`, title: "S", body: "", entry_type: "manuscript:scene", metadata: {} } as unknown as EditableDocument;
  editorPanes.panes = [...editorPanes.panes, pane];
}

describe("editorPanes subordinate-pane cascade", () => {
  beforeEach(() => {
    editorPanes.reset();
  });

  it("tearing down a master closes its registered children", () => {
    scenePane("editor_10");
    const closeChild = vi.fn();
    subordinatePanes.register("schema_type", "editor_10", closeChild);

    editorPanes.tearDown("editor_10");

    expect(closeChild).toHaveBeenCalledTimes(1);
    // Link dropped as it fired — a second teardown of the same id is a no-op.
    subordinatePanes.closeChildrenOf("editor_10");
    expect(closeChild).toHaveBeenCalledTimes(1);
  });

  it("reset() drops subordinate links so a reused pane id can't mis-fire", () => {
    // Project A: a child registered under editor_1.
    const staleClose = vi.fn();
    subordinatePanes.register("editor_2", "editor_1", staleClose);

    // Switch projects — panes are dropped wholesale and the id counter restarts.
    editorPanes.reset();

    // Project B reuses editor_1; closing it must NOT fire the stale project-A link.
    subordinatePanes.closeChildrenOf("editor_1");
    expect(staleClose).not.toHaveBeenCalled();
  });
});
