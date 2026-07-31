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

// A card as the board renders it: identity, the synopsis (the card body), and the
// plotline + scene it points at (each null when unset). A card whose scene was
// deleted projects as unattached (`scene: null`), never a dangling pointer — the
// backend purges referencing cards on delete (ADR §S5).
export type PlotBoardCard = {
  id: string;
  title: string;
  synopsis: string;
  plotline: string | null;
  scene: string | null;
};

// The whole board in one read: the plotlines (lanes), the cards, and the board's
// opaque `layout` payload (card positions / grouping — S7c makes it interactive)
// plus the board id + revision, so a later layout save round-trips without a
// second request.
export type PlotBoardProjection = {
  board_id: string;
  board_revision: string;
  layout: Record<string, unknown>;
  plotlines: PlotBoardPlotline[];
  cards: PlotBoardCard[];
};
