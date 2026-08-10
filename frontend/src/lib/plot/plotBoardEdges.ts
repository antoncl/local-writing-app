// Plot-board edge layers (ADR-0048 S7 Slice 6a) — the PURE projection → SvelteFlow
// edges transform, the sibling of `buildBoardNodes`. The board's dimensions beyond
// position+colour are drawn as toggleable card→card edge LAYERS; this slice ships
// the two DERIVED, read-only layers. The canvas is not headless-testable
// ([[reference_svelteflow_headless_limits]]), so the edge logic lives — and is
// unit-tested — here, and only the compositing is browser-verified.
//
//   - manuscript: the reveal-order spine — cards chained in the order their scenes
//     are read (`card.sequence`, the backend's manuscript reading-order rank).
//   - beats: for each beat a card fulfils, the cards fulfilling THAT beat chained
//     in the order they advance through it.
//
// Derived edges are deliberately QUIET (thin, dashed, no arrowhead — the layout
// already carries direction); the authored causal layer (Slice 6b) reads stronger.
// Both layers can be on at once — holding ≥2 is what the Slice 7 diagnostics need.

import type { Edge } from "@xyflow/svelte";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

// The edge layers a writer can toggle. Slice 6a ships the two derived ones; the
// authored "causal" layer arrives in 6b.
export type EdgeLayer = "manuscript" | "beats";

// The canonical layer list — the toggle UI iterates it, and the pref loader uses
// it as the whitelist so a stale stored layer name (e.g. a future one, on a
// downgrade) is dropped rather than trusted.
export const EDGE_LAYERS: readonly EdgeLayer[] = ["manuscript", "beats"];

// Order cards along a chain: by manuscript reading order (`sequence`), with the
// scene-less cards (no sequence — off-page / unwritten) after every ranked one, in
// their projection order. `order` is the card's index in `projection.cards`, the
// stable tie-break for cards that share a sequence (n cards on one scene) or share
// the "no sequence" bucket.
type Ranked = { card: PlotBoardCard; order: number };

const bySequenceThenOrder = (a: Ranked, b: Ranked): number => {
  const sa = a.card.sequence;
  const sb = b.card.sequence;
  if (sa == null && sb == null) return a.order - b.order;
  if (sa == null) return 1; // scene-less sorts after any ranked card
  if (sb == null) return -1;
  return sa !== sb ? sa - sb : a.order - b.order;
};

// Chain a sorted card run into consecutive directed edges, tagging each with a
// stable id (unique across layers via the `prefix`) and a CSS class the board's
// scoped styles key on (token-based, no inline colour — the style-token guard).
// `sourceHandle`/`targetHandle` name the card node's anchor handles (see
// PlotCardNodeFlow) — xyflow will not render an edge whose handles it can't resolve,
// so these must match the ids the wrapper gives its Handles.
function chain(sorted: Ranked[], prefix: string, className: string): Edge[] {
  const edges: Edge[] = [];
  for (let i = 0; i + 1 < sorted.length; i++) {
    const source = sorted[i].card.id;
    const target = sorted[i + 1].card.id;
    edges.push({
      id: `${prefix}:${source}->${target}`,
      source,
      target,
      sourceHandle: "out",
      targetHandle: "in",
      class: className,
    });
  }
  return edges;
}

// Build the active edge layers for the board. `layers` is the set the writer has
// toggled on (empty → no edges, the quiet default). Deterministic and total: an
// unknown layer contributes nothing; a card missing from a layer's basis is simply
// absent from that chain.
export function buildBoardEdges(projection: PlotBoardProjection, layers: Set<EdgeLayer>): Edge[] {
  const edges: Edge[] = [];
  const ranked: Ranked[] = projection.cards.map((card, order) => ({ card, order }));

  // Manuscript / reveal-order spine: every card with a scene, in reading order.
  // (n cards on one scene share a rank and chain in projection order — a minor,
  // predictable imperfection; the common case is one card per beat / scene.)
  if (layers.has("manuscript")) {
    const spine = ranked.filter((r) => r.card.sequence != null).sort(bySequenceThenOrder);
    edges.push(...chain(spine, "ms", "manuscript-edge"));
  }

  // Beat sequence: one chain per beat, over the cards fulfilling it, ordered by
  // reading order (scene-less cards after). A card in several beats joins each
  // chain. The beat key is the composite (instance, beat_id) a card→beat link is,
  // JSON-encoded so the two ids can never run together into a false match.
  if (layers.has("beats")) {
    const groups = new Map<string, { members: Ranked[]; instance: string; beat: string }>();
    for (const r of ranked) {
      for (const beat of r.card.beats) {
        const key = JSON.stringify([beat.instance_id, beat.beat_id]);
        const group = groups.get(key) ?? { members: [], instance: beat.instance_id, beat: beat.beat_id };
        group.members.push(r);
        groups.set(key, group);
      }
    }
    for (const { members, instance, beat } of groups.values()) {
      members.sort(bySequenceThenOrder);
      edges.push(...chain(members, `beat:${instance}:${beat}`, "beat-edge"));
    }
  }

  return edges;
}
