// Pure (runes-free) helpers for the tiled workspace shell (#155, phase 2):
// built-in layout presets, layout (de)serialization + validation for
// per-project persistence, and the geometry used by responsive
// collapse-to-tabs. Kept out of the rune controller so the tree logic is
// testable in isolation and the controller file stays small.
//
// Everything here operates on plain LayoutNode data — no $state, no DOM.

import type { LayoutNode, PanelId, Split, SplitDir, TabGroup } from "@/lib/types";

// Stable ids for the default groups so HOMES can target them and a persisted
// layout can be reconciled against them. User-created groups get generated ids.
export const G_PROJECT = "g-project";
export const G_DRAFT = "g-draft";
export const G_EDITOR = "g-editor";
export const G_SIDE = "g-side";
export const G_TOOLS = "g-tools";

// Editor documents carry dynamic `editor_*` ids; everything else is a fixed
// region panel. Pure predicate, so it lives here with the rest of the pure code.
export function isEditorPanelId(id: string): boolean {
  return id.startsWith("editor_");
}

// Where a region lands when opened and not already placed. Editor docs are not
// listed — they always home to the editor group. Doubles as the known-region
// allowlist for validating a persisted layout (any tab id that is neither an
// editor doc nor a known region is dropped on load).
export const HOMES: Record<string, string> = {
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

const KNOWN_REGIONS = new Set(Object.keys(HOMES));

function isKnownTab(id: string): boolean {
  return isEditorPanelId(id) || KNOWN_REGIONS.has(id);
}

// --- Node factories -------------------------------------------------------

export function group(id: string, tabs: PanelId[]): TabGroup {
  return { kind: "group", id, tabs: [...tabs], active: tabs[0] ?? null };
}

export function split(id: string, dir: SplitDir, children: LayoutNode[], sizes: number[]): Split {
  return { kind: "split", id, dir, children, sizes };
}

export function normalize(sizes: number[]): number[] {
  const total = sizes.reduce((a, b) => a + b, 0);
  if (total <= 0) return sizes.map(() => 1 / sizes.length);
  return sizes.map((s) => s / total);
}

function cloneNode(node: LayoutNode): LayoutNode {
  if (node.kind === "group") {
    return { kind: "group", id: node.id, tabs: [...node.tabs], active: node.active };
  }
  return { kind: "split", id: node.id, dir: node.dir, children: node.children.map(cloneNode), sizes: [...node.sizes] };
}

// --- Built-in presets -----------------------------------------------------

export type PresetName = "writing" | "schema" | "research";

// The starting "writing" arrangement: Project + Draft stacked left, editor in
// the centre, Lore/Research over TODO/Search on the right. The other presets
// re-anchor the same regions for a schema-authoring or research session. Every
// preset MUST include an empty group with id G_EDITOR so open documents re-home
// into it after the preset is applied. Presets only reference regions that are
// always registered and self-sufficient (no empty schema_type editor).
export const PRESETS: Record<PresetName, () => Split> = {
  writing: () =>
    split("root", "row", [
      split("s-left", "col", [group(G_PROJECT, ["project"]), group(G_DRAFT, ["outline"])], [0.4, 0.6]),
      group(G_EDITOR, []),
      split("s-right", "col", [group(G_SIDE, ["lore", "research"]), group(G_TOOLS, ["todo", "search"])], [0.62, 0.38]),
    ], [0.24, 0.54, 0.22]),
  schema: () =>
    split("root", "row", [
      group(G_DRAFT, ["outline"]),
      group(G_EDITOR, []),
      split("s-right", "col", [group(G_SIDE, ["schema"]), group(G_TOOLS, ["todo", "search"])], [0.62, 0.38]),
    ], [0.2, 0.56, 0.24]),
  research: () =>
    split("root", "row", [
      split("s-left", "col", [group(G_DRAFT, ["outline"]), group("g-research", ["research"])], [0.5, 0.5]),
      group(G_EDITOR, []),
      group(G_SIDE, ["lore"]),
    ], [0.24, 0.54, 0.22]),
};

export function defaultLayout(): Split {
  return PRESETS.writing();
}

const PRESET_NAMES = new Set<string>(Object.keys(PRESETS));

function validPreset(value: unknown): PresetName | null {
  return typeof value === "string" && PRESET_NAMES.has(value) ? (value as PresetName) : null;
}

// --- Serialization --------------------------------------------------------

// `activePreset` is carried so a restored, still-untouched preset keeps its
// menu check mark across a reload (the arrangement alone can't be reverse-mapped
// to a preset name).
export type LayoutSnapshot = {
  version: 1;
  root: Split;
  activeEditorGroupId: string;
  activePreset: PresetName | null;
};

const SNAPSHOT_VERSION = 1 as const;

function eachGroup(node: LayoutNode, visit: (g: TabGroup) => void): void {
  if (node.kind === "group") visit(node);
  else for (const child of node.children) eachGroup(child, visit);
}

// Drop session-ephemeral editor documents from a cloned tree and repair each
// group's active tab (editor docs never rehydrate across a reload).
function stripEditorTabs(node: LayoutNode): void {
  if (node.kind === "group") {
    node.tabs = node.tabs.filter((t) => !isEditorPanelId(t));
    if (!node.active || !node.tabs.includes(node.active)) node.active = node.tabs[0] ?? null;
  } else {
    node.children.forEach(stripEditorTabs);
  }
}

// Prune empty groups (collapsing single-child splits, renormalizing sizes) so a
// persisted or restored tree is minimal — except the editor home, which stays
// even when empty so documents have somewhere to open.
function pruneEmpty(node: LayoutNode, keepId: string): LayoutNode | null {
  if (node.kind === "group") {
    if (node.tabs.length > 0) return node;
    return node.id === keepId || node.id === G_EDITOR ? node : null;
  }
  const kept: LayoutNode[] = [];
  const keptSizes: number[] = [];
  node.children.forEach((child, i) => {
    const result = pruneEmpty(child, keepId);
    if (result) {
      kept.push(result);
      keptSizes.push(node.sizes[i] ?? 1);
    }
  });
  if (kept.length === 0) return null;
  if (kept.length === 1) return kept[0];
  node.children = kept;
  node.sizes = normalize(keptSizes);
  return node;
}

// Resolve which group holds the editor, re-anchoring if the preferred id was
// pruned: prefer the requested id, then a G_EDITOR group, then any empty group,
// then the first group.
function resolveEditorGroupId(root: Split, preferred: string): string {
  const groups: TabGroup[] = [];
  eachGroup(root, (g) => groups.push(g));
  if (groups.some((g) => g.id === preferred)) return preferred;
  const fallback =
    groups.find((g) => g.id === G_EDITOR) ?? groups.find((g) => g.tabs.length === 0) ?? groups[0];
  return fallback?.id ?? G_EDITOR;
}

// Normalize any (cloned + edited) node into a persistable Split with a
// guaranteed editor home. Shared by serialize() and deserialize().
function finalizeTree(node: LayoutNode | null, editorId: string): { root: Split; activeEditorGroupId: string } {
  const pruned = node ? pruneEmpty(node, editorId) : null;
  let root: Split;
  if (!pruned) root = defaultLayout();
  else if (pruned.kind === "group") root = split("root", "row", [pruned], [1]);
  else root = pruned;
  return { root, activeEditorGroupId: resolveEditorGroupId(root, editorId) };
}

// Capture the current tree as a persistable snapshot: region arrangement +
// splitter fractions + a single empty editor home. Editor documents are
// stripped (they are session state, reconstructed on open).
export function serialize(root: Split, activeEditorGroupId: string, activePreset: PresetName | null): LayoutSnapshot {
  const clone = cloneNode(root);
  stripEditorTabs(clone);
  const { root: outRoot, activeEditorGroupId: editorId } = finalizeTree(clone, activeEditorGroupId);
  return { version: SNAPSHOT_VERSION, root: outRoot, activeEditorGroupId: editorId, activePreset: validPreset(activePreset) };
}

// Structurally validate + normalize a node from persisted JSON. Returns a clean
// LayoutNode or null. Unknown region tab ids are dropped; malformed sizes are
// reset to equal shares; degenerate single-child splits collapse.
function validateNode(raw: unknown): LayoutNode | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (o.kind === "group") {
    if (typeof o.id !== "string") return null;
    const tabs = Array.isArray(o.tabs)
      ? [...new Set(o.tabs.filter((t): t is string => typeof t === "string" && isKnownTab(t)))]
      : [];
    const active = typeof o.active === "string" && tabs.includes(o.active) ? o.active : tabs[0] ?? null;
    return { kind: "group", id: o.id, tabs, active };
  }
  if (o.kind === "split") {
    if (typeof o.id !== "string" || (o.dir !== "row" && o.dir !== "col") || !Array.isArray(o.children)) return null;
    const children: LayoutNode[] = [];
    for (const child of o.children) {
      const validated = validateNode(child);
      if (validated) children.push(validated);
    }
    if (children.length === 0) return null;
    if (children.length === 1) return children[0];
    let sizes = Array.isArray(o.sizes)
      ? o.sizes.map((s) => (typeof s === "number" && Number.isFinite(s) && s > 0 ? s : 0))
      : [];
    if (sizes.length !== children.length || sizes.some((s) => s <= 0)) sizes = children.map(() => 1);
    return { kind: "split", id: o.id, dir: o.dir, children, sizes: normalize(sizes) };
  }
  return null;
}

// Parse + validate a persisted snapshot string. Any structural problem yields
// null so the caller can fall back to a preset — a malformed tree never reaches
// the renderer (no NaN flex sizes, no orphaned editor home).
export function deserialize(raw: string | null): LayoutSnapshot | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const obj = parsed as Record<string, unknown>;
  if (obj.version !== SNAPSHOT_VERSION) return null;
  const node = validateNode(obj.root);
  if (!node) return null;
  const preferred = typeof obj.activeEditorGroupId === "string" ? obj.activeEditorGroupId : G_EDITOR;
  const { root, activeEditorGroupId } = finalizeTree(node, preferred);
  return { version: SNAPSHOT_VERSION, root, activeEditorGroupId, activePreset: validPreset(obj.activePreset) };
}

// --- Collapse geometry ----------------------------------------------------

// Minimum useful width per region (design-language §4 extension guarantee). A
// split that can't fit its children at these widths collapses to a tab strip.
export const DEFAULT_MIN_WIDTH = 240;
export const EDITOR_MIN_WIDTH = 360;
// A stacked (col) split needs at least this per row before it collapses.
export const MIN_ROW_HEIGHT = 140;

const MIN_WIDTHS: Record<string, number> = {
  project: 200,
  outline: 220,
  lore: 240,
  research: 240,
  schema: 260,
  schema_type: 260,
  prompts: 260,
  mutations: 260,
  assistants: 260,
  chats: 240,
  todo: 200,
  search: 220,
};

export function minWidthOf(panelId: PanelId): number {
  if (isEditorPanelId(panelId)) return EDITOR_MIN_WIDTH;
  return MIN_WIDTHS[panelId] ?? DEFAULT_MIN_WIDTH;
}

function groupMinWidth(g: TabGroup): number {
  if (g.tabs.length === 0) return g.id === G_EDITOR ? EDITOR_MIN_WIDTH : DEFAULT_MIN_WIDTH;
  return Math.max(...g.tabs.map(minWidthOf));
}

// Minimum size a subtree needs along `dir`: a split along that axis sums its
// children; a split across it takes the max; a group contributes its own min.
export function subtreeMinMain(node: LayoutNode, dir: SplitDir): number {
  if (node.kind === "group") return dir === "row" ? groupMinWidth(node) : MIN_ROW_HEIGHT;
  if (node.dir === dir) {
    return node.children.reduce((sum, child) => sum + subtreeMinMain(child, dir), 0);
  }
  return Math.max(...node.children.map((child) => subtreeMinMain(child, dir)));
}

// Ordered leaf tabs under a subtree — the tab list a collapsed split renders.
export function flattenPanels(node: LayoutNode): PanelId[] {
  if (node.kind === "group") return [...node.tabs];
  return node.children.flatMap(flattenPanels);
}
