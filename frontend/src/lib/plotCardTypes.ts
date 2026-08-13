// Plot card + plotline types (ADR-0048 S5a/S5b; ADR-0053). Kept out of the
// monolithic `types.ts` (at the file-size cap); re-exported from there so
// `@/lib/types` stays the single import barrel. Mirrors the backend `Card*` /
// `Plotline*` models (models/entries.py) field-for-field.
//
// A card (`plot:card`) and a plotline (`plot:plotline` — which IS a plot-template
// instance, ADR-0053 §1) are both book-local layered `plot/` folder nodes with the
// same shape — a title, a prose body, and schema-driven `metadata` (the plotline's
// beats + lineage ride there) — so they share one base here as they do on the
// backend (`_PlotFolder*`). The endpoint is
// the only family discriminator.

import type { EntryMetadata } from "./types";

// The list-row shape (no revision / computed_metadata) — what list_cards /
// list_plotlines return per entry.
type PlotFolderSummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

// The full single-node shape — carries the optimistic-concurrency `revision` and
// the resolved `computed_metadata`. Editing a card means get → mutate → save with
// this revision as the base.
type PlotFolderEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

// A card (ADR-0048 §1): a unit of story function. The `plotline` and `scene`
// refs ride inside `metadata` (single entity_refs); attach/detach is a save that
// sets/clears `metadata.scene`, realize is its own endpoint.
export type CardSummary = PlotFolderSummary;
export type CardEntry = PlotFolderEntry;
export type CardList = { entries: CardSummary[] };

// A plotline (ADR-0048 §2): a story thread — name (title), color (metadata),
// description (body). Cards reference one as their primary plotline; the
// ReferencePicker's `plot` source (#742) draws its candidates from this list.
export type PlotlineSummary = PlotFolderSummary;
export type PlotlineEntry = PlotFolderEntry;
export type PlotlineList = { entries: PlotlineSummary[] };
