// Plot-board projection types (ADR-0048 S7a/S7b) — the read model the PlotEditor
// board renders from. Kept out of the monolithic `types.ts` (at the size cap) and
// re-exported from there so `@/lib/types` stays the single import barrel. Mirrors
// the backend `PlotBoardProjection` (models/entries.py) field-for-field.

// A plotline as the board sees it: a thread — id, title, and a colour swatch id
// for its lane accent / card stripe (null when unset). Never a template link
// (plotline ≠ template_instance — the board renders a thread, not an instance).
export type PlotBoardPlotline = {
  id: string;
  title: string;
  color: string | null;
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

// A card as the board renders it: identity, the synopsis (the card body), the
// plotline + scene it points at (each null when unset), and its innermost
// manuscript `container` (the box it lays out inside — null when homeless, i.e.
// no scene or a scene under the root). A card whose scene was deleted projects as
// unattached (`scene: null`) and homeless (`container: null`), never a dangling
// pointer — the backend purges referencing cards on delete (ADR §S5). `container`
// is derived from the scene, never authored: dragging a card never re-homes it.
export type PlotBoardCard = {
  id: string;
  title: string;
  synopsis: string;
  plotline: string | null;
  scene: string | null;
  container: string | null;
};

// The whole board in one read: the plotlines (colour threads), the manuscript
// containers (the structural boxes), the cards, and the board's opaque `layout`
// payload (card positions — S7c makes it interactive) plus the board id +
// revision, so a later layout save round-trips without a second request.
export type PlotBoardProjection = {
  board_id: string;
  board_revision: string;
  layout: Record<string, unknown>;
  plotlines: PlotBoardPlotline[];
  containers: PlotBoardContainer[];
  cards: PlotBoardCard[];
};

// A point on the board canvas.
export type BoardXY = { x: number; y: number };

// The board's opaque `layout` payload, as S7c shapes it: per-card position
// overrides keyed by card id. A card absent from `positions` falls back to its
// derived lane-grid default; once the layout is saved, every card is pinned
// here. Lane headers are always derived (fixed), so they never appear.
export type PlotBoardLayout = {
  positions?: Record<string, BoardXY>;
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
