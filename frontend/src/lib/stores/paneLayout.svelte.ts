// Floating-pane window manager — owns the geometry (position/size/z-order) of
// every pane, the drag/resize interaction, and editor-pane placement. Extracted
// from App.svelte (#14 P0), which was a god-shell carrying this alongside the
// editor/autosave/schema concerns. This is the LAYOUT slice only — pane CONTENT
// (drafts, documents, the save lifecycle) stays in App / the editorPanes domain.
//
// Singleton: the app mounts one shell, so a single module-level instance with
// rune fields is correct and idiomatic. Not a writable store — a controller with
// traceable methods (see docs/frontend-architecture.md).
//
// GOTCHA (AGENTS.md): the drag/resize path deliberately uses document-level
// mousemove/mouseup listeners plus direct DOM style writes to move/resize panes
// reliably in the local browser runtime. Do NOT "simplify" it — re-test drag
// and resize live in the real app after any change here.

import type { PaneId, PaneState } from "@/lib/types";

// Editor panes carry dynamic `editor_*` ids; everything else is a fixed
// singleton pane. Pure predicate, so it lives outside the instance.
export function isEditorPaneId(id: string): boolean {
  return id.startsWith("editor_");
}

class PaneLayout {
  // Position/size/z-order for every pane, keyed by id. Pure UI state — preserved
  // across project switches (only the editor-id counter resets; see App).
  panes = $state<Record<PaneId, PaneState>>({
    project: { title: "Project", x: 18, y: 18, width: 380, height: 340, z: 1 },
    outline: { title: "Draft", x: 18, y: 260, width: 300, height: 420, z: 2 },
    lore: { title: "Lore", x: 330, y: 260, width: 300, height: 320, z: 3 },
    research: { title: "Research", x: 650, y: 260, width: 300, height: 320, z: 3 },
    schema: { title: "Detail Types", x: 330, y: 260, width: 360, height: 420, z: 3 },
    schema_type: { title: "Detail Type", x: 708, y: 260, width: 440, height: 560, z: 4 },
    prompts: { title: "Prompts", x: 330, y: 260, width: 360, height: 420, z: 3 },
    transformations: { title: "Transformations", x: 360, y: 280, width: 360, height: 420, z: 3 },
    assistants: { title: "Assistants", x: 330, y: 260, width: 340, height: 420, z: 3 },
    chats: { title: "Chats", x: 330, y: 260, width: 320, height: 420, z: 3 },
    todo: { title: "TODO", x: 1126, y: 18, width: 310, height: 320, z: 4 },
    search: { title: "Search", x: 1126, y: 360, width: 310, height: 320, z: 5 },
  });

  // z-order high-water mark — only ever climbs, never reset.
  nextZ = 10;
  // Monotonic id source for editor panes; reset per project via resetEditorIndex().
  nextEditorPaneIndex = 1;

  // Live interaction state. Plain fields (not runes): the drag/resize handlers
  // write the DOM directly for smoothness and commit to `panes` at the end.
  #dragState: { id: PaneId; element: HTMLElement; offsetX: number; offsetY: number } | null = null;
  #resizeState:
    | { id: PaneId; element: HTMLElement; startX: number; startY: number; startWidth: number; startHeight: number }
    | null = null;

  // Injected by App: raising a pane that is the focused editor pane also updates
  // focusedEditorPaneId. The hook keeps this controller ignorant of editor state.
  onRaise: ((id: PaneId) => void) | null = null;

  // The inline `style` string for a pane (position/size/z). Computed on demand;
  // reading `panes[id]` makes consumers reactive to drag/resize commits.
  styleFor(id: PaneId): string {
    const pane = this.panes[id];
    if (!pane) return "";
    return `left: ${pane.x}px; top: ${pane.y}px; width: ${pane.width}px; height: ${pane.height}px; z-index: ${pane.z};`;
  }

  // Clamp every pane back inside the viewport (called on mount / open).
  fitToViewport(): void {
    const margin = 8;
    this.panes = Object.fromEntries(
      Object.entries(this.panes).map(([id, pane]) => [
        id,
        {
          ...pane,
          x: Math.min(pane.x, Math.max(margin, window.innerWidth - pane.width - margin)),
          y: Math.min(pane.y, Math.max(margin, window.innerHeight - 48)),
        },
      ]),
    ) as Record<PaneId, PaneState>;
  }

  // Bring a pane to the front. Writes the DOM z-index directly (the live drag UI
  // bypasses reactivity) and fires onRaise for the editor-focus side effect.
  raise(id: PaneId): void {
    this.nextZ += 1;
    const z = this.nextZ;
    this.panes = { ...this.panes, [id]: { ...this.panes[id], z } };
    const pane = document.querySelector<HTMLElement>(`.pane[data-pane-id="${id}"]`);
    if (pane) pane.style.zIndex = String(z);
    this.onRaise?.(id);
  }

  headerKeydown(event: KeyboardEvent, id: PaneId): void {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    this.raise(id);
  }

  resizeKeydown(event: KeyboardEvent, id: PaneId): void {
    const step = event.shiftKey ? 40 : 12;
    const pane = this.panes[id];
    let width = pane.width;
    let height = pane.height;
    if (event.key === "ArrowRight") width += step;
    else if (event.key === "ArrowLeft") width -= step;
    else if (event.key === "ArrowDown") height += step;
    else if (event.key === "ArrowUp") height -= step;
    else return;

    event.preventDefault();
    const minWidth = isEditorPaneId(id) ? 440 : 240;
    const minHeight = isEditorPaneId(id) ? 320 : 170;
    this.panes = {
      ...this.panes,
      [id]: { ...pane, width: Math.max(minWidth, width), height: Math.max(minHeight, height) },
    };
  }

  startDrag(event: MouseEvent, id: PaneId): void {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const element = (event.currentTarget as HTMLElement).closest<HTMLElement>(".pane");
    if (!element) return;
    this.raise(id);
    this.#dragState = {
      id,
      element,
      offsetX: event.clientX - element.offsetLeft,
      offsetY: event.clientY - element.offsetTop,
    };
    document.addEventListener("mousemove", this.#movePane);
    document.addEventListener("mouseup", this.#stopDrag, { once: true });
  }

  #movePane = (event: MouseEvent): void => {
    if (!this.#dragState) return;
    const margin = 8;
    const pane = this.panes[this.#dragState.id];
    const maxX = Math.max(margin, window.innerWidth - 88);
    const maxY = Math.max(margin, window.innerHeight - 48);
    const x = Math.min(Math.max(margin, event.clientX - this.#dragState.offsetX), maxX);
    const y = Math.min(Math.max(margin, event.clientY - this.#dragState.offsetY), maxY);
    this.#dragState.element.style.left = `${x}px`;
    this.#dragState.element.style.top = `${y}px`;
    this.panes = {
      ...this.panes,
      [this.#dragState.id]: { ...pane, x, y },
    };
  };

  #stopDrag = (): void => {
    this.#dragState = null;
    document.removeEventListener("mousemove", this.#movePane);
    document.removeEventListener("mouseup", this.#stopDrag);
  };

  startResize(event: MouseEvent, id: PaneId): void {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const element = (event.currentTarget as HTMLElement).closest<HTMLElement>(".pane");
    if (!element) return;
    this.raise(id);
    this.#resizeState = {
      id,
      element,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: element.offsetWidth,
      startHeight: element.offsetHeight,
    };
    document.addEventListener("mousemove", this.#resizeMove);
    document.addEventListener("mouseup", this.#stopResize, { once: true });
  }

  #resizeMove = (event: MouseEvent): void => {
    if (!this.#resizeState) return;
    const minWidth = isEditorPaneId(this.#resizeState.id) ? 440 : 240;
    const minHeight = isEditorPaneId(this.#resizeState.id) ? 320 : 170;
    const width = Math.max(minWidth, this.#resizeState.startWidth + event.clientX - this.#resizeState.startX);
    const height = Math.max(minHeight, this.#resizeState.startHeight + event.clientY - this.#resizeState.startY);
    this.#resizeState.element.style.width = `${width}px`;
    this.#resizeState.element.style.height = `${height}px`;
    this.panes = {
      ...this.panes,
      [this.#resizeState.id]: { ...this.panes[this.#resizeState.id], width, height },
    };
  };

  #stopResize = (): void => {
    this.#resizeState = null;
    document.removeEventListener("mousemove", this.#resizeMove);
    document.removeEventListener("mouseup", this.#stopResize);
  };

  // Allocate geometry + a fresh id for a new editor pane (cascading offset by
  // how many are already open); returns the id. The EditorPaneState itself is
  // created by App (editor domain).
  allocateEditorPane(existingCount: number): string {
    const id = `editor_${this.nextEditorPaneIndex}`;
    this.nextEditorPaneIndex += 1;
    const offset = Math.min(160, existingCount * 28);
    this.panes = {
      ...this.panes,
      [id]: { title: "Editor", x: 342 + offset, y: 18 + offset, width: 760, height: 662, z: this.nextZ + 1 },
    };
    this.nextZ += 1;
    return id;
  }

  // Auto-fit an editor pane's height to its rendered content, after a tick so
  // the DOM has laid out. Queries `.editor-panel` — editor-pane specific.
  fitEditorPaneToContent(paneId: string): void {
    setTimeout(() => {
      const paneEl = document.querySelector<HTMLElement>(`[data-pane-id="${paneId}"]`);
      if (!paneEl) return;
      const headerEl = paneEl.querySelector<HTMLElement>(".pane-header");
      const panelEl = paneEl.querySelector<HTMLElement>(".editor-panel");
      if (!headerEl || !panelEl) return;
      let contentHeight = 0;
      for (const child of Array.from(panelEl.children)) {
        const el = child as HTMLElement;
        if (el.offsetParent === null) continue;
        contentHeight += el.getBoundingClientRect().height;
      }
      const totalHeight = headerEl.getBoundingClientRect().height + contentHeight + 24;
      const current = this.panes[paneId];
      if (!current || totalHeight < 120) return;
      const newHeight = Math.round(totalHeight);
      this.panes = {
        ...this.panes,
        [paneId]: { ...current, height: newHeight },
      };
      paneEl.style.height = `${newHeight}px`;
    }, 100);
  }

  // Drop a pane's geometry when its editor pane is torn down.
  removePane(id: PaneId): void {
    const { [id]: _removed, ...rest } = this.panes;
    this.panes = rest as Record<PaneId, PaneState>;
  }

  // Restart the editor-pane id sequence on project switch. Pane positions are
  // preserved (pure UI state); only the `editor_*` counter resets.
  resetEditorIndex(): void {
    this.nextEditorPaneIndex = 1;
  }

  // Remove any lingering document listeners (App unmount / shutdown).
  dispose(): void {
    document.removeEventListener("mousemove", this.#movePane);
    document.removeEventListener("mouseup", this.#stopDrag);
    document.removeEventListener("mousemove", this.#resizeMove);
    document.removeEventListener("mouseup", this.#stopResize);
  }
}

export const paneLayout = new PaneLayout();
