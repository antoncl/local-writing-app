// Editor-pane id allocation + focus shim. This once owned the floating-MDI
// geometry (absolute x/y/width/height/z per pane + document-level drag/resize);
// that is gone with the tiled workspace shell (#32 — see workspaceLayout). What
// remains is the small surface editorPanes still routes through here: minting
// `editor_*` ids for new document panes, and a `raise` that fires `onRaise` so
// App can track the focused editor document. The tiled layout mirrors the open
// panes and their focus into tabs (App's reconcile/focus effects).

// Editor panes carry dynamic `editor_*` ids; everything else is a fixed
// singleton pane. Pure predicate, so it lives outside the instance.
export function isEditorPaneId(id: string): boolean {
  return id.startsWith("editor_");
}

class PaneLayout {
  // Monotonic id source for editor panes; reset per project via resetEditorIndex().
  nextEditorPaneIndex = 1;

  // Injected by App: raising a pane that is the focused editor pane updates
  // focusedEditorPaneId. Keeps this controller ignorant of editor state.
  onRaise: ((id: string) => void) | null = null;

  // Mint a fresh id for a new editor pane. (The geometry this used to allocate
  // is obsolete under the tiled shell; the layout store places the pane.)
  allocateEditorPane(_existingCount: number): string {
    const id = `editor_${this.nextEditorPaneIndex}`;
    this.nextEditorPaneIndex += 1;
    return id;
  }

  // Focus a pane — fires the editor-focus side effect. No z-order under tiling.
  raise(id: string): void {
    this.onRaise?.(id);
  }

  // No-ops kept so editorPanes' call sites stay unchanged: geometry teardown and
  // content-fit are meaningless once panes are tiled tabs, not floating boxes.
  removePane(_id: string): void {}
  fitEditorPaneToContent(_paneId: string): void {}

  // Restart the editor-pane id sequence on project switch.
  resetEditorIndex(): void {
    this.nextEditorPaneIndex = 1;
  }

  dispose(): void {}
}

export const paneLayout = new PaneLayout();
