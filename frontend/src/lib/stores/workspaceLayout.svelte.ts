// Tiled workspace shell (#32) — owns the split-tree that tiles every region and
// editor document edge to edge. Replaces the floating-MDI geometry that used to
// live in paneLayout.svelte.ts (absolute x/y/width/height/z + document-level
// drag/resize of free-floating boxes). Here nothing floats, overlaps, or
// cascades: the tree fills the workspace, splitters resize siblings, and panels
// stack as tabs (design-language §4, surface taxonomy).
//
// Singleton controller (the app mounts one shell). Not a writable store — a
// rune-backed object with traceable methods (docs/frontend-architecture.md).
//
// The tree is a $state root; operations mutate it in place (Svelte 5 deep
// proxies make nested mutation reactive) and reassign scalars where needed. All
// nodes carry a stable id so the renderer can address them for splitter drag.

import type { LayoutNode, PanelId, Split, SplitDir, TabGroup } from "@/lib/types";

// Stable ids for the default groups so `HOMES` can target them and a persisted
// layout can be reconciled against them later (#155). User-created groups get
// generated ids.
const G_PROJECT = "g-project";
const G_DRAFT = "g-draft";
const G_EDITOR = "g-editor";
const G_SIDE = "g-side";
const G_TOOLS = "g-tools";

// Editor documents carry dynamic `editor_*` ids; everything else is a fixed
// region panel. Pure predicate — lives outside the instance.
export function isEditorPanelId(id: string): boolean {
  return id.startsWith("editor_");
}

// Where a region lands when opened and not already placed. Editor docs are not
// listed — they always home to the editor group (see homeGroupFor).
const HOMES: Record<string, string> = {
  project: G_PROJECT,
  outline: G_DRAFT,
  lore: G_SIDE,
  research: G_SIDE,
  schema: G_SIDE,
  schema_type: G_SIDE,
  prompts: G_SIDE,
  mutations: G_SIDE,
  assistants: G_SIDE,
  chats: G_SIDE,
  todo: G_TOOLS,
  search: G_TOOLS,
};

function group(id: string, tabs: PanelId[]): TabGroup {
  return { kind: "group", id, tabs: [...tabs], active: tabs[0] ?? null };
}

function split(id: string, dir: SplitDir, children: LayoutNode[], sizes: number[]): Split {
  return { kind: "split", id, dir, children, sizes };
}

// The starting arrangement — a "writing" layout: Project + Draft stacked on the
// left, the editor in the centre, Lore/Research over TODO/Search on the right.
// On-demand regions (prompts, mutations, assistants, chats, schema) are absent
// until opened, when they join their home group.
function defaultLayout(): Split {
  return split("root", "row", [
    split("s-left", "col", [group(G_PROJECT, ["project"]), group(G_DRAFT, ["outline"])], [0.4, 0.6]),
    group(G_EDITOR, []),
    split("s-right", "col", [group(G_SIDE, ["lore", "research"]), group(G_TOOLS, ["todo", "search"])], [0.62, 0.38]),
  ], [0.24, 0.54, 0.22]);
}

class WorkspaceLayout {
  root = $state<Split>(defaultLayout());

  // Which group receives a newly opened editor document, and the panel the user
  // last focused (drives tab highlight + editor focus side effects).
  activeEditorGroupId = $state<string>(G_EDITOR);
  focusedPanel = $state<PanelId | null>(null);

  // Live tab drag-and-drop (rearrange). `dragging` is the panel under the
  // cursor; `dropZone` is the group + region the drop would land in, so the
  // renderer can paint the target overlay.
  dragging = $state<PanelId | null>(null);
  dropZone = $state<{ groupId: string; zone: "center" | "left" | "right" | "top" | "bottom" } | null>(null);

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
    return this.groupById(homeId) ?? this.groupById(G_SIDE) ?? this.allGroups()[0];
  }

  // --- Placement ----------------------------------------------------------

  // Ensure a panel is in the tree and activate it. Idempotent: an already-placed
  // panel is just re-activated + focused. New panels join their home group.
  ensureVisible(panelId: PanelId): void {
    let g = this.groupOf(panelId);
    if (!g) {
      g = this.#homeGroupFor(panelId);
      g.tabs.push(panelId);
    }
    g.active = panelId;
    this.focus(panelId);
  }

  activate(panelId: PanelId): void {
    const g = this.groupOf(panelId);
    if (!g) return;
    g.active = panelId;
    this.focus(panelId);
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
    if (!next) this.root = defaultLayout();
    else if (next.kind === "group") this.root = split("root", "row", [next], [1]);
    else this.root = next;
  }

  // --- Interactions -------------------------------------------------------

  // Commit new fractional sizes for a split after a splitter drag. The live
  // drag writes flex-grow to the DOM directly (Workspace); this persists it.
  commitSizes(splitId: string, sizes: number[]): void {
    const target = this.#findSplit(this.root, splitId);
    if (target) target.sizes = normalize(sizes);
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
    if (src.id === target.id) {
      const from = src.tabs.indexOf(panelId);
      src.tabs.splice(from, 1);
      const to = beforeIndex === undefined ? src.tabs.length : clampInsert(beforeIndex, from, src.tabs.length);
      src.tabs.splice(to, 0, panelId);
      src.active = panelId;
      return;
    }
    src.tabs.splice(src.tabs.indexOf(panelId), 1);
    if (src.active === panelId) src.active = src.tabs[src.tabs.length - 1] ?? null;
    target.tabs.splice(beforeIndex ?? target.tabs.length, 0, panelId);
    target.active = panelId;
    this.#maybePrune(src.id);
    this.focus(panelId);
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

    src.tabs.splice(src.tabs.indexOf(panelId), 1);
    if (src.active === panelId) src.active = src.tabs[src.tabs.length - 1] ?? null;

    const fresh = group(this.#newId("g"), [panelId]);
    const dir: SplitDir = edge === "left" || edge === "right" ? "row" : "col";
    const before = edge === "left" || edge === "top";
    this.#insertBeside(targetGroupId, fresh, dir, before);

    if (src.id !== target.id) this.#maybePrune(src.id);
    this.focus(panelId);
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

  // Restore the default arrangement (used by "reset layout" and on the first
  // project open before saved layouts land in #155).
  reset(): void {
    this.root = defaultLayout();
    this.activeEditorGroupId = G_EDITOR;
    this.focusedPanel = null;
  }
}

function normalize(sizes: number[]): number[] {
  const total = sizes.reduce((a, b) => a + b, 0);
  if (total <= 0) return sizes.map(() => 1 / sizes.length);
  return sizes.map((s) => s / total);
}

// Adjust an insertion index for a same-group move once the source item has been
// spliced out (indices after the removed slot shift left by one).
function clampInsert(beforeIndex: number, removedFrom: number, len: number): number {
  const adjusted = beforeIndex > removedFrom ? beforeIndex - 1 : beforeIndex;
  return Math.max(0, Math.min(adjusted, len));
}

export const workspaceLayout = new WorkspaceLayout();
