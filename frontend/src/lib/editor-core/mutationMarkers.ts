// Mutation markers in an accepted AI draft (#2424). The built-in Draft scene
// prompt briefs the scene's mutation pills and asks the model to write
// `⟦<anchor id>⟧` at the point each change happens. On accept, each existing
// pill MOVES to its marker — one transaction that inserts the same node (same
// attrs, so MutationPasteReconciler keeps the id) and deletes the original, so
// the doc never holds two copies. Never mints ids: this is a move, not an insert.
import type { EditorState, Transaction } from "@tiptap/pm/state";
import type { Node as PMNode } from "@tiptap/pm/model";

// Ids are `mut_` + 12 hex from createMutationId, but legacy anchors derived
// server-side (`<unit id>_<digest>`) and the Math.random fallback can differ,
// so the id alphabet is wider than the minted shape. The ⟦ ⟧ delimiters bound it.
export const MUTATION_MARKER_PATTERN = /⟦(mut_[A-Za-z0-9_-]+)⟧/g;

export interface MarkerPlacement {
  /** Null when the range held no markers — nothing to dispatch. */
  tr: Transaction | null;
  /** Ids whose pill moved to its (first) marker. */
  moved: string[];
  /** Ids that matched no pill in the doc; their marker text was removed. */
  unknown: string[];
}

export function hasMutationMarker(text: string): boolean {
  return text.includes("⟦mut_");
}

interface MarkerHit {
  from: number;
  to: number;
  id: string;
}

interface Op {
  from: number;
  to: number;
  insert: PMNode | null;
}

/** Build the single transaction that places every pill named by a marker inside
 *  `range` and strips the marker text. Positions are all in pre-transaction
 *  coordinates; ops apply highest-first so earlier ones stay valid. */
export function placeMutationMarkers(
  state: EditorState,
  range: { from: number; to: number },
): MarkerPlacement {
  const hits: MarkerHit[] = [];
  state.doc.nodesBetween(range.from, range.to, (node, pos) => {
    if (!node.isText || !node.text) return true;
    const start = Math.max(range.from, pos);
    const end = Math.min(range.to, pos + node.nodeSize);
    const text = node.text.slice(start - pos, end - pos);
    for (const m of text.matchAll(MUTATION_MARKER_PATTERN)) {
      const from = start + (m.index ?? 0);
      hits.push({ from, to: from + m[0].length, id: m[1] });
    }
    return true;
  });
  if (hits.length === 0) return { tr: null, moved: [], unknown: [] };

  const pills = new Map<string, { pos: number; node: PMNode }>();
  state.doc.descendants((node, pos) => {
    const key =
      node.type.name === "mutation"
        ? node.attrs.anchorId
        : node.type.name === "mutationClose"
          ? node.attrs.closeId
          : null;
    if (key && !pills.has(String(key))) pills.set(String(key), { pos, node });
    return true;
  });

  hits.sort((a, b) => a.from - b.from);
  const ops: Op[] = [];
  const moved: string[] = [];
  const unknown: string[] = [];
  const placed = new Set<string>();
  for (const hit of hits) {
    const pill = pills.get(hit.id);
    if (pill && !placed.has(hit.id)) {
      placed.add(hit.id);
      moved.push(hit.id);
      ops.push({ from: hit.from, to: hit.to, insert: pill.node });
      ops.push({ from: pill.pos, to: pill.pos + pill.node.nodeSize, insert: null });
    } else {
      if (!pill && !unknown.includes(hit.id)) unknown.push(hit.id);
      ops.push({ from: hit.from, to: hit.to, insert: null });
    }
  }

  const tr = state.tr;
  for (const op of ops.sort((a, b) => b.from - a.from)) {
    if (op.insert) tr.replaceWith(op.from, op.to, op.insert);
    else tr.delete(op.from, op.to);
  }
  return { tr, moved, unknown };
}

/** The short, plain-words notice for a placement — null when nothing happened. */
export function markerNotice(moved: number, unknown: number): string | null {
  const parts: string[] = [];
  if (moved > 0) parts.push(`Placed ${moved} ${moved === 1 ? "change" : "changes"} in the draft.`);
  if (unknown > 0) {
    parts.push(
      unknown === 1
        ? "1 marker didn't match a change in this scene and was removed."
        : `${unknown} markers didn't match a change in this scene and were removed.`,
    );
  }
  return parts.length ? parts.join(" ") : null;
}
