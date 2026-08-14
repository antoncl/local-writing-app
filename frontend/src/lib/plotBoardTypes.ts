// Plot-board projection types (ADR-0048 S7a/S7b) — the read model the PlotEditor
// board renders from. Kept out of the monolithic `types.ts` (at the size cap) and
// re-exported from there so `@/lib/types` stays the single import barrel. Mirrors
// the backend `PlotBoardProjection` (models/entries.py) field-for-field.

// A beat on a plotline node (ADR-0053 §3): its stable id (the card→beat link target),
// title, and `use_count` — how many story cards fulfil it (ADR-0053 §6 / S5a; a 0 is a
// gap the structure exposes). The plotline node renders these as its roster with the count.
export type PlotBoardPlotlineBeat = {
  beat_id: string;
  title: string;
  use_count: number;
};

// A plotline as the board sees it (ADR-0053 §1): a thread that IS a plot-template
// instance — id, title, a colour swatch id (null when unset), and its ordered beat
// roster. The board renders the plotline as a node holding these beats (S2), and a
// card's beat badges resolve against them.
export type PlotBoardPlotline = {
  id: string;
  title: string;
  color: string | null;
  beats: PlotBoardPlotlineBeat[];
};

// A manuscript container (an act, a chapter — whatever the project declares) as a
// soft, free-flow board box (ADR-0048 S7 Slice 4). `parent` is the enclosing
// container's id, or null when its parent is the manuscript root (a top-level act),
// so the board nests a chapter box inside its act. Only containers that hold a
// placed card (plus their ancestors) are projected, in manuscript reading order.
// Structure, not thread — no colour (plotline is the colour axis, orthogonal).
export type PlotBoardContainer = {
  id: string;
  title: string;
  parent: string | null;
};

// A card→beat link resolved for the board (ADR-0048 S7 Slice 5b; ADR-0053): a beat
// the card fulfils, with its title + owning plotline title for the badge + tooltip.
// The stored link is only ids; the projection resolves the titles, so the board
// renders labels directly. A link whose plotline/beat is gone is never projected.
// `plotline_color` is the owning plotline's swatch id (null when it has none), so a
// card can tint each beat badge by its plotline — same-plotline beats share a colour,
// disambiguating collisions between same-named beats of different plotlines.
export type PlotBoardBeat = {
  plotline_id: string;
  plotline_title: string;
  plotline_color: string | null;
  beat_id: string;
  title: string;
  // The beat's 1-based position in its plotline roster (#941), resolved by the
  // backend so the badge shows a stable number that disambiguates same-titled beats.
  number: number;
};

// A card as the board renders it: identity, the synopsis (the card body), the
// plotline + scene it points at (each null when unset), and its innermost
// manuscript `container` (the box it lays out inside — null when homeless, i.e.
// no scene or a scene under the root). A card whose scene was deleted projects as
// unattached (`scene: null`) and homeless (`container: null`), never a dangling
// pointer — the backend purges referencing cards on delete (ADR §S5). `container`
// is derived from the scene, never authored: dragging a card never re-homes it.
//
// `page_status` (Slice 5b) is whether the card is realized in prose: `on_page`
// (derived — a scene is attached), the authored `off_page` / `unwritten`, or null
// (the sparse default → unwritten). Derived from the current scene, so a stale
// stored `on_page` never reaches the board. `beats` are the card's resolved beat
// links — the badges it wears (empty when it fulfils none).
//
// `sequence` (Slice 6) is the card's scene's manuscript reading-order rank
// (0-based), or null when it has no scene — an off-page / unwritten card holds no
// reveal-order position. The manuscript-order edge layer chains cards by this
// rank; the beat-sequence layer orders a beat's cards by it.
//
// `causal_links` (Slice 6b) are the ids of the cards this card *leads to* — the
// author-drawn causal edges (each a live card id; self / gone targets already
// dropped backend-side). The causal edge layer draws one directed edge per id.
export type PlotBoardCard = {
  id: string;
  title: string;
  synopsis: string;
  plotline: string | null;
  scene: string | null;
  container: string | null;
  page_status: string | null;
  beats: PlotBoardBeat[];
  sequence: number | null;
  causal_links: string[];
};

// The directed causal edge a `causal_inversion` finding points at — `source` *leads
// to* `target`. The board highlights this exact edge (matched against the causal
// edge id `buildBoardEdges` mints per link).
export type PlotDiagnosticEdge = {
  source: string;
  target: string;
};

// A card a diagnostic names: its id (to light on the canvas) and title (for the
// finding's prose). Denormalised so the panel renders + drives the highlight without
// re-joining against the card list.
export type PlotDiagnosticCard = {
  id: string;
  title: string;
};

// One cross-dimension finding (ADR-0048 S7 — the payoff): a place where two plot
// layers disagree, or a beat the structure leaves unfilled. Deterministic, derived
// backend-side from reveal order, beat rosters, and causal edges (no LLM — that is
// S7b). `kind` is `causal_inversion` (a card sets up a card revealed earlier — `edge`
// + `cards` = [setup, payoff]), `beat_inversion` (within one plotline a later beat is
// fully revealed before an earlier begins — `plotline_id` + `beat_ids` name the two),
// or `beat_gap` (an interior beat no card fulfils — `plotline_id` + `beat_ids`, `cards`
// empty). `id` is a stable key (kind + participant ids) so the panel keeps a selection
// across refetches.
export type PlotDiagnostic = {
  id: string;
  kind: 'causal_inversion' | 'beat_inversion' | 'beat_gap';
  message: string;
  cards: PlotDiagnosticCard[];
  edge: PlotDiagnosticEdge | null;
  plotline_id: string | null;
  beat_ids: string[];
};

// The whole board in one read: the plotlines (colour threads), the manuscript
// containers (the structural boxes), the cards, and the board's opaque `layout`
// payload (card positions — S7c makes it interactive) plus the board id +
// revision, so a later layout save round-trips without a second request.
// `diagnostics` (S7) is the derived cross-dimension findings — a facet of this same
// read, refreshed with every projection fetch so the panel is live.
export type PlotBoardProjection = {
  board_id: string;
  board_revision: string;
  layout: Record<string, unknown>;
  plotlines: PlotBoardPlotline[];
  containers: PlotBoardContainer[];
  cards: PlotBoardCard[];
  diagnostics: PlotDiagnostic[];
};

// A point on the board canvas.
export type BoardXY = { x: number; y: number };

// A container's manual size (#878): its stored width/height in board coords. A
// container is otherwise a soft backdrop (auto-wraps its cards); a stored size is a
// MINIMUM the box never shrinks below — content still grows it past this, but it holds
// the extra room when content is smaller. That is the whole point: a single-card box
// (and so its member cards' drag extent, #874) gets room to spread. Keyed by container id.
export type BoardSize = { w: number; h: number };

// The board's opaque `layout` payload: per-node position overrides keyed by node id
// — cards and plotline nodes alike (their ids are distinct, so one map holds both).
// A node absent from `positions` falls back to its derived slot; once dragged and
// saved, it is pinned here. Container boxes carry no position (their origin is always
// derived), so they never appear in `positions` — but a resized container's manual
// size (#878) is pinned in `sizes`, keyed by container id. Absent → the box auto-wraps.
export type PlotBoardLayout = {
  positions?: Record<string, BoardXY>;
  sizes?: Record<string, BoardSize>;
};

// The board singleton as the save endpoint (`PUT /api/plot/board`) returns it
// (ADR-0048 §3). S7c reads back only the advanced `revision` — the next save's
// optimistic base.
export type PlotBoard = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  layout: Record<string, unknown>;
};
