// Plot-template types (ADR-0048 S4b/S4c). Kept out of the monolithic `types.ts`
// (which is at the file-size cap); re-exported from there so `@/lib/types` stays
// the single import barrel.
//
// A `plot:template` is a diagnostic story-structure lens shipped by the built-in
// Library (ADR-0049) or an owned clone. Its beat roster is the `beats` ordered-list
// metadata field (S7 Slice 1, #736) — edited via MetadataPanel like any field; the
// `template` spec carries the remaining template-level attributes (opaque to the
// editor — it round-trips verbatim), and the prose guide is the body. The Library
// provenance fields mirror PromptEntry exactly, so the same read-only-in-place lock,
// clone, and hide affordances apply.

import type { EntryMetadata } from "./types";

export type PlotTemplateSourceRef = {
  id: string;
  title: string;
  url?: string | null;
  citation?: string;
  note?: string;
  metadata?: EntryMetadata;
};

export type PlotTemplateSpec = {
  version?: number;
  slug: string;
  display_name: string;
  aliases?: string[];
  family?: string;
  description?: string;
  cultural_context?: string;
  prescriptiveness?: string;
  ai_use_guidance?: string;
  global_diagnostic_questions?: string[];
  source_refs?: PlotTemplateSourceRef[];
  ip_risk?: string;
  builtin_policy?: string;
  template_version?: string;
  locale?: string;
  metadata?: EntryMetadata;
};

export type PlotTemplateSummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  template: PlotTemplateSpec;
  // The size of the beat roster — what the palette shows as "7 beats". The roster
  // itself is not on the summary (the picker only needs the count).
  beat_count?: number;
  source_layer_id?: string;
  source_layer_label?: string;
  // True when shipped by the app-owned built-in Library (ADR-0049). Clone/hide
  // branch on this, not on the display label. Mirrors PromptEntrySummary.
  is_library?: boolean;
  // Backend's fail-closed read-only-in-place verdict (#689): false when the
  // template is inherited and a save would 409. Read via `readOnlyInPlace`.
  editable?: boolean;
};

export type PlotTemplate = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  template: PlotTemplateSpec;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  is_library?: boolean;
  // See PlotTemplateSummary.editable (#689).
  editable?: boolean;
};

export type PlotTemplateList = {
  entries: PlotTemplateSummary[];
};
