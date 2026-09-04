import type { PlotTemplateSummary } from "@/lib/types";

// The plot-template sections shared by the spawn palette (PlotTemplatePalette) and the
// management pane (PlotTemplates): character arcs split off first (ADR-0080 slice 2), then
// the remaining plotline templates divide into genre-shaped spines and genre-agnostic story
// structures so a newcomer meets a few labelled buckets, not a flat wall of ~11 names.
//
// `family` isn't a schema field the view evaluator reads, so this is a plain partition, not a
// view group_by. Both surfaces share this one definition rather than each hand-rolling the
// set — the taxonomy has a single home.

// Genre-shaped plot families: a mystery (`puzzle`), thriller (`genre`), or romance
// (`relationship`) spine. Everything else is a genre-agnostic "story structure".
export const GENRE_FAMILIES: ReadonlySet<string> = new Set(["puzzle", "genre", "relationship"]);

export type PlotTemplateGroups = {
  structures: PlotTemplateSummary[];
  genre: PlotTemplateSummary[];
  arcs: PlotTemplateSummary[];
};

// Partition templates into the three sections in one pass. Disjoint and exhaustive: every
// entry lands in exactly one bucket. A missing/unknown family (an author's `custom`, or a
// future family) falls through to `structures`, the catch-all plotline bucket.
export function groupPlotTemplates(entries: PlotTemplateSummary[]): PlotTemplateGroups {
  const structures: PlotTemplateSummary[] = [];
  const genre: PlotTemplateSummary[] = [];
  const arcs: PlotTemplateSummary[] = [];
  for (const entry of entries) {
    const family = entry.template?.family ?? "";
    if (family === "character_arc") arcs.push(entry);
    else if (GENRE_FAMILIES.has(family)) genre.push(entry);
    else structures.push(entry);
  }
  return { structures, genre, arcs };
}
