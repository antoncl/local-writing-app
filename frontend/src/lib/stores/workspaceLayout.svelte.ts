// Tiled workspace shell (#32) — owns the split-tree that tiles every region and
// editor document edge to edge. Replaces the old floating-MDI geometry (absolute
// x/y/width/height/z + document-level drag/resize of free-floating boxes; the
// paneLayout shim that held it is gone, #157). Here nothing floats, overlaps, or
// cascades: the tree fills the workspace, splitters resize siblings, and panels
// stack as tabs (design-language §4, surface taxonomy).
//
// Singleton controller (the app mounts one shell). Not a writable store — a
// rune-backed object with traceable methods (docs/frontend-architecture.md).
//
// The tree is a $state root; operations mutate it in place (Svelte 5 deep
// proxies make nested mutation reactive) and reassign scalars where needed. All
// nodes carry a stable id so the renderer can address them for splitter drag.
//
// Phase 2 (#155) adds per-project persistence, named presets, and keyboard
// focus. The pure tree/preset/serialization logic lives in
// workspaceLayout.serialize.ts; this file owns the reactive state + side effects.

import type { LayoutNode, PanelId, Split, SplitDir, TabGroup } from "@/lib/types";
import {
  G_EDITOR,
  G_SIDE,
  HOMES,
  PRESETS,
  defaultLayout,
  deserialize,
  group,
  isEditorPanelId,
  normalize,
  serialize,
  split,
  type LayoutSnapshot,
  type PresetName,
} from "./workspaceLayout.serialize";

// Re-exported so consumers keep importing it from the controller module.
export { isEditorPanelId };

const STORAGE_PREFIX = "workspaceLayout:"; // + project path
const PERSIST_DEBOUNCE_MS = 400;

class WorkspaceLayout {
  root = $state<Split>(defaultLayout());

  // Which group receives a newly opened editor document, and the panel the user
  // last focused (drives tab highlight + editor focus side effects).
  activeEditorGroupId = $state<string>(G_EDITOR);
  focusedPanel = $state<PanelId | null>(null);

  // The built-in preset the current arrangement matches, or null once the user
  // has rearranged into a custom layout (drives the Layout menu's check mark).
  activePreset = $state<PresetName | null>("writing");

  // Live tab drag-and-drop (rearrange). `dragging` is the panel under the
  // cursor; `dropZone` is the group + region the drop would land in, so the
  // renderer can paint the target overlay.
  dragging = $state<PanelId | null>(null);
  dropZone = $state<{ groupId: string; zone: "center" | "left" | "right" | "top" | "bottom" } | null>(null);

  // Tile zoom (#219, ADR-0038 §F): the group maximized to fill the whole shell,
  // or null at rest. tmux-zoom semantics — the split tree is retained untouched;
  // the renderer just paints this one group full-bleed and re-tiles when it
  // clears. Ephemeral: never serialized, so a saved layout re-opens un-zoomed.
  zoomedGroupId = $state<string | null>(null);

  // localStorage key for the open project's layout, or null with none open.
  #storageKey: string | null = null;
  #persistTimer: ReturnType<typeof setTimeout> | null = null;

  beginDrag(panelId: PanelId): void {
    this.dragging = panelId;
    this.dropZone = null;
  }

  setDropZone(groupId: string, zone: "center" | "left" | "right" | "top" | "bottom"): void {
    if (this.dropZone?.groupId === groupId && this.dropZone?.zone === zone) return;
    this.dropZone = { groupId, zone };
  }

  // Commit the in-progress drag onto the current drop zone and clear drag state.
  drop(): void {
    const panelId = this.dragging;
    const target = this.dropZone;
    this.endDrag();
    if (!panelId || !target) return;
    if (target.zone === "center") this.moveTab(panelId, target.groupId);
    else this.dropOnEdge(panelId, target.groupId, target.zone);
  }

  endDrag(): void {
    this.dragging = null;
    this.dropZone = null;
  }

  // --- Tile zoom ----------------------------------------------------------

  // Toggle maximize for a specific tile (the pane-title glyph).
  toggleZoom(groupId: string): void {
    this.zoomedGroupId = this.zoomedGroupId === groupId ? null : groupId;
  }

  // Toggle maximize for the tile holding the focused panel (keyboard). Falls
  // back to the active editor group when nothing is focused yet.
  toggleZoomFocused(): void {
    if (this.zoomedGroupId) {
      this.zoomedGroupId = null;
      return;
    }
    const g =
      (this.focusedPanel ? this.groupOf(this.focusedPanel) : null) ??
      this.groupById(this.activeEditorGroupId);
    if (g) this.zoomedGroupId = g.id;
  }

  // Drop a stale zoom target after a structural change removed its group, so a
  // pruned tile can't leave the shell stuck on a group that no longer exists.
  #clearZoomIfMissing(): void {
    if (this.zoomedGroupId && !this.groupById(this.zoomedGroupId)) {
      this.zoomedGroupId = null;
    }
  }

  #idSeq = 1;
  #newId(prefix: string): string {
    this.#idSeq += 1;
    return `${prefix}-${this.#idSeq}`;
  }

  // Raising a panel that is an editor document must also update editor focus;
  // App injects this so the controller stays ignorant of editor state.
  onFocusPanel: ((id: PanelId) => void) | null = null;

  // --- Tree queries -------------------------------------------------------

  #eachGroup(node: LayoutNode, visit: (g: TabGroup) => void): void {
    if (node.kind === "group") visit(node);
    else for (const child of node.children) this.#eachGroup(child, visit);
  }

  allGroups(): TabGroup[] {
    const out: TabGroup[] = [];
    this.#eachGroup(this.root, (g) => out.push(g));
    return out;
  }

  groupById(id: string): TabGroup | null {
    let found: TabGroup | null = null;
    this.#eachGroup(this.root, (g) => {
      if (g.id === id) found = g;
    });
    return found;
  }

  // The group currently holding a panel, or null if it isn't placed.
  groupOf(panelId: PanelId): TabGroup | null {
    let found: TabGroup | null = null;
    this.#eachGroup(this.root, (g) => {
      if (g.tabs.includes(panelId)) found = g;
    });
    return found;
  }

  isPlaced(panelId: PanelId): boolean {
    return this.groupOf(panelId) !== null;
  }

  #homeGroupFor(panelId: PanelId): TabGroup {
    if (isEditorPanelId(panelId)) {
      return this.groupById(this.activeEditorGroupId) ?? this.groupById(G_EDITOR) ?? this.allGroups()[0];
    }
    const homeId = HOMES[panelId] ?? G_SIDE;
    const existing = this.groupById(homeId);
    if (existing) return existing;
    // The region's home column was pruned away (e.g. both permanent regions
    // dragged out of it). Recreate a dedicated group for it on the right edge
    // rather than dumping the region into an unrelated group's tabs (#155).
    const fresh = group(homeId, []);
    this.#appendColumn(fresh);
    return fresh;
  }

  // Add a fresh group as a new column at the end of the root row split.
  #appendColumn(g: TabGroup): void {
    const share = this.root.children.length > 0 ? 1 / (this.root.children.length + 1) : 1;
    this.root.children.push(g);
    this.root.sizes.push(share);
    this.root.sizes = normalize([...this.root.sizes]);
  }

  // --- Placement ----------------------------------------------------------

  // Ensure a panel is in the tree and activate it. Idempotent: an already-placed
  // panel is just re-activated + focused. New panels join their home group.
  ensureVisible(panelId: PanelId): void {
    let g = this.groupOf(panelId);
    if (!g) {
      g = this.#homeGroupFor(panelId);
      g.tabs.push(panelId);
      // Placing a region (not just opening a document) is a layout change.
      if (!isEditorPanelId(panelId)) this.#markCustom();
    }
    g.active = panelId;
    this.focus(panelId);
    this.#schedulePersist();
  }

  activate(panelId: PanelId): void {
    const g = this.groupOf(panelId);
    if (!g) return;
    g.active = panelId;
    this.focus(panelId);
    // The active tab is part of the persisted layout (region tab selection, e.g.
    // Lore vs Research). Editor-tab churn is stripped on serialize + debounced.
    this.#schedulePersist();
  }

  focus(panelId: PanelId): void {
    this.focusedPanel = panelId;
    const g = this.groupOf(panelId);
    if (g && isEditorPanelId(panelId)) this.activeEditorGroupId = g.id;
    this.onFocusPanel?.(panelId);
  }

  // Remove a panel from the tree. Picks a neighbouring tab as the group's new
  // active; prunes the group (and collapses its parent split) if it empties.
  removePanel(panelId: PanelId): void {
    const g = this.groupOf(panelId);
    if (!g) return;
    const idx = g.tabs.indexOf(panelId);
    g.tabs.splice(idx, 1);
    if (g.active === panelId) {
      g.active = g.tabs[Math.min(idx, g.tabs.length - 1)] ?? null;
    }
    this.#maybePrune(g.id);
    if (this.focusedPanel === panelId) this.focusedPanel = null;
    if (!isEditorPanelId(panelId)) this.#markCustom();
    this.#schedulePersist();
  }

  // Prune an emptied group unless it is the perennial editor group — the editor
  // is the primary region and must persist (showing a placeholder) even with no
  // document open, since new documents home to it.
  #maybePrune(groupId: string): void {
    if (groupId === G_EDITOR) return;
    const g = this.groupById(groupId);
    if (g && g.tabs.length === 0) this.#pruneGroup(groupId);
  }

  // Drop an empty group out of the tree and collapse any split left with one
  // child (that child takes the split's place; sizes renormalize automatically).
  #pruneGroup(groupId: string): void {
    const removeFrom = (node: LayoutNode): LayoutNode | null => {
      if (node.kind === "group") return node.id === groupId ? null : node;
      const kept: LayoutNode[] = [];
      const keptSizes: number[] = [];
      node.children.forEach((child, i) => {
        const result = removeFrom(child);
        if (result) {
          kept.push(result);
          keptSizes.push(node.sizes[i]);
        }
      });
      if (kept.length === 0) return null;
      if (kept.length === 1) return kept[0];
      node.children = kept;
      node.sizes = normalize(keptSizes);
      return node;
    };
    const next = removeFrom(this.root);
    // Root always stays a split so the shell has a stable container; if it
    // collapsed to a single group, wrap it back into a 1-child row split.
    if (!next) {
      // The tree emptied out — rebuilding the default is the writing preset.
      this.root = defaultLayout();
      this.activeEditorGroupId = G_EDITOR;
      this.activePreset = "writing";
    } else if (next.kind === "group") {
      this.root = split("root", "row", [next], [1]);
    } else {
      this.root = next;
    }
    this.#clearZoomIfMissing();
  }

  // --- Interactions -------------------------------------------------------

  // Commit new fractional sizes for a split after a splitter drag. The live
  // drag writes flex-grow to the DOM directly (Workspace); this persists it. A
  // resize keeps the active-preset identity (only rearranging clears it).
  commitSizes(splitId: string, sizes: number[]): void {
    const target = this.#findSplit(this.root, splitId);
    if (target) target.sizes = normalize(sizes);
    this.#schedulePersist();
  }

  #findSplit(node: LayoutNode, id: string): Split | null {
    if (node.kind === "group") return null;
    if (node.id === id) return node;
    for (const child of node.children) {
      const found = this.#findSplit(child, id);
      if (found) return found;
    }
    return null;
  }

  // Move a tab within/between groups (reorder or relocate). `beforeIndex` is the
  // insertion point in the target group (defaults to end).
  moveTab(panelId: PanelId, targetGroupId: string, beforeIndex?: number): void {
    const target = this.groupById(targetGroupId);
    if (!target) return;
    const src = this.groupOf(panelId);
    if (!src) return;
    this.#markCustom();
    if (src.id === target.id) {
      const from = src.tabs.indexOf(panelId);
      src.tabs.splice(from, 1);
      const to = beforeIndex === undefined ? src.tabs.length : clampInsert(beforeIndex, from, src.tabs.length);
      src.tabs.splice(to, 0, panelId);
      src.active = panelId;
      this.#schedulePersist();
      return;
    }
    src.tabs.splice(src.tabs.indexOf(panelId), 1);
    if (src.active === panelId) src.active = src.tabs[src.tabs.length - 1] ?? null;
    target.tabs.splice(beforeIndex ?? target.tabs.length, 0, panelId);
    target.active = panelId;
    this.#maybePrune(src.id);
    this.focus(panelId);
    this.#schedulePersist();
  }

  // Drop a tab onto an edge of a target group → create a new group holding the
  // panel and place it on that edge, wrapping the target in a split of the right
  // orientation (or extending an existing one).
  dropOnEdge(panelId: PanelId, targetGroupId: string, edge: "left" | "right" | "top" | "bottom"): void {
    const target = this.groupById(targetGroupId);
    if (!target) return;
    const src = this.groupOf(panelId);
    if (!src) return;
    // No-op: dropping the only tab of a group back onto itself.
    if (src.id === target.id && src.tabs.length === 1) return;

    this.#markCustom();
    src.tabs.splice(src.tabs.indexOf(panelId), 1);
    if (src.active === panelId) src.active = src.tabs[src.tabs.length - 1] ?? null;

    const fresh = group(this.#newId("g"), [panelId]);
    const dir: SplitDir = edge === "left" || edge === "right" ? "row" : "col";
    const before = edge === "left" || edge === "top";
    this.#insertBeside(targetGroupId, fresh, dir, before);

    if (src.id !== target.id) this.#maybePrune(src.id);
    this.focus(panelId);
    this.#schedulePersist();
  }

  // Place `fresh` next to the group `neighbourId` along `dir`. If the group's
  // parent split already runs that way, insert as a sibling; otherwise wrap the
  // group in a new split. Root stays the outermost node.
  #insertBeside(neighbourId: string, fresh: TabGroup, dir: SplitDir, before: boolean): void {
    const parent = this.#parentOf(this.root, neighbourId);
    if (parent && parent.dir === dir) {
      const at = parent.children.findIndex((c) => c.kind === "group" && c.id === neighbourId);
      const insertAt = before ? at : at + 1;
      // Split the neighbour's slot in half between it and the newcomer.
      const share = parent.sizes[at] / 2;
      parent.sizes[at] = share;
      parent.children.splice(insertAt, 0, fresh);
      parent.sizes.splice(insertAt, 0, share);
      parent.sizes = normalize(parent.sizes);
      return;
    }
    // Wrap the neighbour group in a fresh split of `dir`.
    const replaceIn = (node: LayoutNode): LayoutNode => {
      if (node.kind === "group") {
        if (node.id !== neighbourId) return node;
        const pair = before ? [fresh, node] : [node, fresh];
        return split(this.#newId("s"), dir, pair, [0.5, 0.5]);
      }
      node.children = node.children.map(replaceIn);
      return node;
    };
    const next = replaceIn(this.root);
    this.root = next.kind === "split" ? next : split("root", "row", [next], [1]);
  }

  #parentOf(node: LayoutNode, childId: string): Split | null {
    if (node.kind === "group") return null;
    if (node.children.some((c) => c.id === childId)) return node;
    for (const child of node.children) {
      const found = this.#parentOf(child, childId);
      if (found) return found;
    }
    return null;
  }

  // --- Keyboard focus -----------------------------------------------------

  // Focus the Nth tab-group in document order (Ctrl/Cmd+1…9). Returns the
  // group's id so the caller can move DOM focus onto it, or null if out of range.
  focusGroupByIndex(index: number): string | null {
    const groups = this.allGroups();
    const g = groups[index];
    if (!g) return null;
    const tab = g.active ?? g.tabs[0] ?? null;
    if (tab) this.focus(tab);
    else this.focusedPanel = null;
    return g.id;
  }

  // Cycle focus to the next/previous tab-group (F6 / Shift+F6). Returns the
  // newly focused group's id, or null when there are no groups.
  cycleFocus(direction: 1 | -1): string | null {
    const groups = this.allGroups();
    if (groups.length === 0) return null;
    const current = this.focusedPanel ? this.groupOf(this.focusedPanel) : null;
    const at = current ? groups.findIndex((g) => g.id === current.id) : -1;
    const next = (at + direction + groups.length) % groups.length;
    return this.focusGroupByIndex(next);
  }

  // --- Presets + persistence ----------------------------------------------

  // Replace the whole arrangement with a built-in preset. Open editor documents
  // re-home into the new editor group via App's reconcile effect.
  applyPreset(name: PresetName): void {
    const factory = PRESETS[name];
    if (!factory) return;
    this.root = factory();
    this.activeEditorGroupId = G_EDITOR;
    this.activePreset = name;
    this.focusedPanel = null;
    this.zoomedGroupId = null;
    this.#schedulePersist();
  }

  // Apply a saved snapshot (a user preset). Round-trips through serialize() to
  // clone + normalize, so applying the same stored snapshot twice never aliases
  // its nodes into reactive state. A user preset is a custom layout (no built-in
  // check mark), so activePreset clears.
  applySnapshot(snap: LayoutSnapshot): void {
    const fresh = serialize(snap.root, snap.activeEditorGroupId, null);
    this.root = fresh.root;
    this.activeEditorGroupId = fresh.activeEditorGroupId;
    this.activePreset = null;
    this.focusedPanel = null;
    this.zoomedGroupId = null;
    this.#schedulePersist();
  }

  // Capture the current arrangement for saving as a named user preset.
  snapshot(): LayoutSnapshot {
    return serialize(this.root, this.activeEditorGroupId, this.activePreset);
  }

  // Restore the open project's saved layout (or the writing preset on a miss).
  loadForProject(path: string): void {
    this.#flushPersist();
    this.zoomedGroupId = null;
    this.#storageKey = path ? STORAGE_PREFIX + path : null;
    let snap: LayoutSnapshot | null = null;
    try {
      snap = this.#storageKey ? deserialize(localStorage.getItem(this.#storageKey)) : null;
    } catch {
      snap = null;
    }
    if (snap) {
      this.root = snap.root;
      this.activeEditorGroupId = snap.activeEditorGroupId;
      // Restore the preset identity so an untouched preset keeps its check mark.
      this.activePreset = snap.activePreset;
      this.focusedPanel = null;
    } else {
      // No saved layout yet — start from the writing preset (and persist it).
      this.applyPreset("writing");
    }
  }

  // Flush any pending write and detach from the project's storage key. Leaves
  // the tree on the default so the no-project state is clean.
  closeForProject(): void {
    this.#flushPersist();
    this.#storageKey = null;
    this.reset();
  }

  #markCustom(): void {
    this.activePreset = null;
  }

  #schedulePersist(): void {
    if (!this.#storageKey) return;
    if (this.#persistTimer !== null) clearTimeout(this.#persistTimer);
    this.#persistTimer = setTimeout(() => {
      this.#persistTimer = null;
      this.#persistNow();
    }, PERSIST_DEBOUNCE_MS);
  }

  #flushPersist(): void {
    if (this.#persistTimer !== null) {
      clearTimeout(this.#persistTimer);
      this.#persistTimer = null;
      this.#persistNow();
    }
  }

  #persistNow(): void {
    if (!this.#storageKey) return;
    try {
      localStorage.setItem(this.#storageKey, JSON.stringify(serialize(this.root, this.activeEditorGroupId, this.activePreset)));
    } catch {
      // Storage disabled / quota — layout persistence is best-effort.
    }
  }

  // Restore the default arrangement ("Reset layout" + the no-project state).
  reset(): void {
    this.root = defaultLayout();
    this.activeEditorGroupId = G_EDITOR;
    this.activePreset = "writing";
    this.focusedPanel = null;
    this.zoomedGroupId = null;
    this.#schedulePersist();
  }
}

// Adjust an insertion index for a same-group move once the source item has been
// spliced out (indices after the removed slot shift left by one).
function clampInsert(beforeIndex: number, removedFrom: number, len: number): number {
  const adjusted = beforeIndex > removedFrom ? beforeIndex - 1 : beforeIndex;
  return Math.max(0, Math.min(adjusted, len));
}

export const workspaceLayout = new WorkspaceLayout();
