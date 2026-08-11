// A navigable submenu tree derived from prompt TITLES (#832). A `/` in a prompt
// title encodes menu structure: prompts titled "Revise/Tone" and "Revise/Length"
// collapse into a **Revise** group opening to {Tone, Length}. Purely a
// presentation transform — the stored title is never touched; only the menu
// rendering reads this tree. A title with no `/` stays a flat top-level item, so
// a project with no `/` in any title renders exactly the old flat menu.
//
// This is the shared layer sitting on top of `promptEntriesForSurface` (which has
// already applied the surface/hidden filters): the tree is built from whatever
// survives that filter, so a hidden leaf is simply absent and a group with no
// surviving leaves never forms. Consumed by the drill-down PromptMenu renderer.
//
// Decisions pinned on #832 (2026-08-11):
//  - Parse: split on "/", trim each segment, drop empties → "A / B" ≡ "A/B".
//    Arbitrary depth. A title that reduces to zero segments (pure "/" / blank)
//    falls back to its raw title as one flat leaf, so no prompt is ever swallowed.
//  - Leaf-that-is-also-a-parent ("A" alongside "A/B") → group **A** → {A, B}: a
//    node is never a dual-affordance row. A prompt terminating on a node that also
//    has children is pushed down into a same-labelled leaf child.
//  - Ordering: alpha by label, case-insensitive, per level (matches the flat sort).

import type { PromptEntrySummary } from "@/lib/types";

export interface MenuNode {
  // The segment shown for this row.
  label: string;
  // Set iff this is a runnable leaf (a real prompt). A group node leaves it unset.
  entry?: PromptEntrySummary;
  // Non-empty iff this is a group the menu drills into. Mutually exclusive with a
  // populated `entry` — a node never both runs and opens.
  children: MenuNode[];
}

// Split a title into its menu path. Exported so the equivalence rule lives in one
// place with its tests: "A / B / C", "A/B/C" and "A//B/" all normalise here.
export function parseTitlePath(title: string): string[] {
  return title
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

interface TrieNode {
  label: string;
  // Prompts whose path terminates exactly here. Usually one; more than one only
  // when two prompts share an identical title (kept as separate leaves, not lost).
  entries: PromptEntrySummary[];
  children: Map<string, TrieNode>;
}

function sortNodes(nodes: MenuNode[]): MenuNode[] {
  return nodes.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
}

// A node is a group when it has child paths OR carries more than one terminal
// prompt (duplicate titles). A group never runs itself: any prompt terminating on
// it becomes a same-labelled leaf child (the "A" → {A, B} rule, and duplicates).
function convert(node: TrieNode): MenuNode {
  const childNodes = [...node.children.values()].map(convert);
  const isGroup = childNodes.length > 0 || node.entries.length > 1;
  if (!isGroup) {
    return { label: node.label, entry: node.entries[0], children: [] };
  }
  const selfLeaves = node.entries.map(
    (entry): MenuNode => ({ label: node.label, entry, children: [] }),
  );
  return { label: node.label, children: sortNodes([...childNodes, ...selfLeaves]) };
}

export function buildPromptMenuTree(entries: readonly PromptEntrySummary[]): MenuNode[] {
  const root: TrieNode = { label: "", entries: [], children: new Map() };
  for (const entry of entries) {
    const path = parseTitlePath(entry.title);
    // Degenerate title (no usable segment) keeps its raw title as one flat item.
    const segments = path.length > 0 ? path : [entry.title];
    let node = root;
    for (const segment of segments) {
      let child = node.children.get(segment);
      if (!child) {
        child = { label: segment, entries: [], children: new Map() };
        node.children.set(segment, child);
      }
      node = child;
    }
    node.entries.push(entry);
  }
  return sortNodes([...root.children.values()].map(convert));
}
