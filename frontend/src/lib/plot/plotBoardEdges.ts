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

import { MarkerType, type Edge } from "@xyflow/svelte";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

// The edge layers a writer can toggle. Slice 6a shipped the two DERIVED ones;
// Slice 6b adds the AUTHORED "causal" layer (the "leads to" edges a writer draws).
export type EdgeLayer = "manuscript" | "beats" | "causal";

// The canonical layer list — the toggle UI iterates it, and the pref loader uses
// it as the whitelist so a stale stored layer name (e.g. a future one, on a
// downgrade) is dropped rather than trusted.
export const EDGE_LAYERS: readonly EdgeLayer[] = ["manuscript", "beats", "causal"];

// The card node's anchor-handle ids. xyflow will not render an edge unless its
// `sourceHandle`/`targetHandle` resolve to real Handles on the endpoint nodes, so
// these MUST match the ids `PlotCardNodeFlow` gives its Handles. Single-sourced
// here (and asserted in the tests) precisely because a drift between the two
// silently kills every edge and can't be caught headlessly.
export const CARD_SOURCE_HANDLE = "out";
export const CARD_TARGET_HANDLE = "in";

// The causal arrowhead's colour. xyflow renders an ArrowClosed marker with an
// inline `style:fill`, so a CSS var resolves here (it cascades from `:root`); the
// marker defaults to `fill: none` (invisible) when no colour is passed, so this
// MUST be set. A design token, not a literal — the accent, matching the causal
// edge's stroke so head and line read as one stroke.
export const CAUSAL_MARKER_COLOR = "var(--accent)";

// The out-of-order causal arrowhead's colour (Slice 7): the `--warn` amber, so a
// warning edge's head reads the same as its stroke (recoloured amber via the
// `.causal-warn` scoped rule). A token, matching CAUSAL_MARKER_COLOR's contract.
export const CAUSAL_WARN_COLOR = "var(--warn)";

// The `data` a causal edge carries to PlotCausalEdge (Slice 7). `outOfOrder` is the
// setup-after-payoff diagnostic — the cause is revealed AFTER its effect in reading
// order; the titles let the edge compose a concrete why/what-to-do message without a
// second lookup. Only causal edges carry this; the derived layers have no `data`.
export type CausalEdgeData = {
  outOfOrder: boolean;
  sourceTitle: string;
  targetTitle: string;
};

// The why + what-to-do copy an out-of-order causal edge shows (Slice 7). Pure and
// exported so the sentence the reader actually sees is unit-testable — the edge can't
// mount headlessly ([[reference_svelteflow_headless_limits]]), so this is the only
// place the copy is covered. Names both cards so the warning is concrete, not a
// generic colour (the decoration-must-explain decision).
export function causalWarnMessage(sourceTitle: string, targetTitle: string): string {
  return `Out of reveal order: “${sourceTitle}” leads to “${targetTitle}”, but its scene is read later — the cause lands after its effect. Move “${sourceTitle}” earlier in the manuscript, or reconsider the link.`;
}

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
      sourceHandle: CARD_SOURCE_HANDLE,
      targetHandle: CARD_TARGET_HANDLE,
      class: className,
      // Derived edges are read-only — not selectable/deletable, so a Delete key only
      // ever removes an AUTHORED causal edge (#824), never a computed layer edge.
      selectable: false,
      deletable: false,
    });
  }
  return edges;
}

// Beat-sequence chains (the "beats" layer): one chain per (plotline, beat_id) group,
// over the cards fulfilling that beat, in reading order (scene-less cards after). A card
// fulfilling several beats joins each chain. The beat key is the composite (plotline,
// beat_id) a card→beat link is, JSON-encoded so the two ids can never run together into
// a false match.
function beatChains(ranked: Ranked[]): Edge[] {
  const groups = new Map<string, { members: Ranked[]; plotline: string; beat: string }>();
  for (const r of ranked) {
    for (const beat of r.card.beats) {
      const key = JSON.stringify([beat.plotline_id, beat.beat_id]);
      const group = groups.get(key) ?? { members: [], plotline: beat.plotline_id, beat: beat.beat_id };
      group.members.push(r);
      groups.set(key, group);
    }
  }
  const edges: Edge[] = [];
  for (const { members, plotline, beat } of groups.values()) {
    members.sort(bySequenceThenOrder);
    edges.push(...chain(members, `beat:${plotline}:${beat}`, "beat-edge"));
  }
  return edges;
}

// Build the active edge layers for the board. `layers` is the set the writer has
// toggled on (empty → no edges, the quiet default). Deterministic and total: an
// unknown layer contributes nothing; a card missing from a layer's basis is simply
// absent from that chain. `focusedPlotlineId` (S5b; #911) is the per-plotline FOCUS:
// when set, every edge is dimmed (`edge-dimmed`) so the thread's outlined cards (lit in
// PlotCardNode) pop — focus draws no edges of its own.
export function buildBoardEdges(
  projection: PlotBoardProjection,
  layers: Set<EdgeLayer>,
  focusedPlotlineId?: string | null,
): Edge[] {
  const edges: Edge[] = [];
  const ranked: Ranked[] = projection.cards.map((card, order) => ({ card, order }));

  // Manuscript / reveal-order spine: every card with a scene, in reading order.
  // (n cards on one scene share a rank and chain in projection order — a minor,
  // predictable imperfection; the common case is one card per beat / scene.)
  if (layers.has("manuscript")) {
    const spine = ranked.filter((r) => r.card.sequence != null).sort(bySequenceThenOrder);
    edges.push(...chain(spine, "ms", "manuscript-edge"));
  }

  // Beat sequence: every plotline's beat chains (see beatChains).
  if (layers.has("beats")) {
    edges.push(...beatChains(ranked));
  }

  // Authored causal layer: one DIRECTED edge per "leads to" target. Unlike the
  // derived layers this is not a chain — each link stands alone — and it reads
  // STRONGER (solid, accent, arrow-headed) because the direction is the author's
  // assertion, not an artefact of layout, so the edge carries a `markerEnd`
  // arrowhead the derived layers omit. Skip a target that isn't a live card or is
  // the card itself (defensive; the backend heals these) so a stale projection can
  // never emit a dangling or self edge.
  //
  // Slice 7 cross-dimension diagnostic — setup-after-payoff: when the source's
  // reveal-order rank is AFTER the target's (`source.sequence > target.sequence`),
  // the cause is revealed after its effect. That edge is flagged out-of-order and
  // recoloured `--warn`; PlotCausalEdge decorates it with a why/what-to-do marker.
  // The check reads the cards' `sequence` directly (both dimensions live in the same
  // projection), so it fires whenever causal edges are drawn — never gated on the
  // manuscript layer being toggled on. Cards with no scene (null sequence) hold no
  // reveal position, so an edge touching one is never out of order.
  if (layers.has("causal")) {
    const byId = new Map(projection.cards.map((c) => [c.id, c]));
    for (const card of projection.cards) {
      for (const targetId of card.causal_links) {
        const target = byId.get(targetId);
        if (targetId === card.id || !target) continue;
        const outOfOrder =
          card.sequence != null && target.sequence != null && card.sequence > target.sequence;
        const data: CausalEdgeData = {
          outOfOrder,
          sourceTitle: card.title,
          targetTitle: target.title,
        };
        edges.push({
          id: `causal:${card.id}->${targetId}`,
          source: card.id,
          target: targetId,
          sourceHandle: CARD_SOURCE_HANDLE,
          targetHandle: CARD_TARGET_HANDLE,
          // The custom edge (PlotCausalEdge) renders the same path + a hover-× to
          // remove the link; the class keeps the token stroke/arrowhead styling, and
          // `causal-warn` swaps the stroke to `--warn` for an out-of-order edge.
          type: "causal",
          class: outOfOrder ? "causal-edge causal-warn" : "causal-edge",
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: outOfOrder ? CAUSAL_WARN_COLOR : CAUSAL_MARKER_COLOR,
          },
          data,
          // Authored → the only selectable/deletable edges: click to select, Delete to
          // remove the "leads to" link (#824, PlotEditor.onDeleteCausal).
          selectable: true,
          deletable: true,
        });
      }
    }
  }

  // Per-plotline FOCUS (ADR-0053 §6; #911): focus is a CARD treatment — PlotCardNode
  // OUTLINES the thread's cards (lit) and dims the rest, matching the mockup. Focus draws
  // NO edges of its own: the earlier per-beat focus chain lit an edge only where a beat
  // had 2+ cards, so one-card-per-beat threads showed nothing but a lone "first beat"
  // segment. Here every existing edge (any toggled layer) simply RECEDES so the outlined
  // thread pops.
  if (focusedPlotlineId) {
    for (const e of edges) {
      e.class = `${e.class ?? ""} edge-dimmed`.trim();
    }
  }

  return edges;
}
