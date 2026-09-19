// Peek-card content model (#2011). Pure — no I/O, no Svelte imports — so
// PeekCard.svelte and every hover site build the same view-model from one
// function. `buildPeekTarget` reuses the exact machinery a row already draws
// on: `summaryValues` (#2008, the row-detail synthesis) for the field grid,
// and `projectReferences` (the reverse reference index) for a tag's carrier
// count/breakdown.
import { summaryValues, type SummaryValue } from "@/lib/utils/summaryFields";
import { projectReferences } from "@/lib/views/referenceIndex";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

// Structural, not `refResolve.ts`'s exact `ResolvedRef` union: a caller's own
// resolved-ref shape (e.g. ReferencePicker's `RefNode`, which widens `kind` to
// the full `NodePickerRef` union for its "missing" fallback) is accepted as
// long as it carries these fields — `buildPeekTarget` only ever compares
// `kind` to the literal `"tag"` and passes the rest through untouched.
export type PeekableRef = {
  id: string;
  kind: string;
  title: string;
  entry_type?: string;
  metadata?: EntryMetadata;
};

export type TagKindBreakdown = { kind: string; count: number };

export type PeekTarget = {
  id: string;
  kind: string;
  entryType?: string;
  title: string;
  /** The entry type's display name ("Character"), falling back to the raw
   *  entry_type or the kind when the schema has no name for it. */
  typeLabel: string;
  /** summaryValues() output, uncapped — the caller (PeekCard) decides how
   *  many rows to show. Empty when the ref carries no metadata. */
  summary: SummaryValue[];
  /** Present only for a `tag`-kind ref. */
  tag?: {
    vocabularyLabel: string;
    carriers: number;
    byKind: TagKindBreakdown[];
  };
};

export type PeekTargetDeps = {
  /** The same id → node walk the host already built (`buildRefResolver`) —
   *  reused both to resolve a summary `entity_ref` field's title, and to
   *  bucket a tag's carriers by their own kind. */
  resolveRef: (id: string) => PeekableRef | null;
  /** The project-wide reverse reference index. Required only for a tag's
   *  carrier count/breakdown; omitted elsewhere it reads as zero carriers. */
  referenceIndex?: ReadonlyMap<string, ReadonlySet<string>> | null;
  /** Canonicalizes a possibly-merged tag id before the carrier lookup — pass
   *  `(id) => canonicalIdIn($tagById, id)`. Identity when omitted (an
   *  already-canonical id, or a fixture with no merge to resolve). */
  canonicalTagId?: (id: string) => string;
};

const KIND_LABEL: Record<string, string> = {
  manuscript: "Scene",
  lore: "Lore",
  snippet: "Prompt",
  assistant: "Assistant",
  plot: "Plotline",
  tag: "Tag",
};

/** Display label for a referrer's kind in a tag's breakdown row — mirrors
 *  NodePicker's chip-label vocabulary; "Other" for anything unresolved. */
export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? (kind === "other" ? "Other" : kind);
}

export function buildPeekTarget(ref: PeekableRef, schema: MetadataSchema | null, deps: PeekTargetDeps): PeekTarget {
  const def = ref.entry_type ? schema?.entry_types[ref.entry_type] : undefined;
  const typeLabel = def?.name ?? ref.entry_type ?? ref.kind;
  const resolveTitle = (id: string) => deps.resolveRef(id)?.title;
  const summary = schema ? summaryValues(def, schema, ref.metadata ?? {}, resolveTitle) : [];

  const target: PeekTarget = {
    id: ref.id,
    kind: ref.kind,
    entryType: ref.entry_type,
    title: ref.title,
    typeLabel,
    summary,
  };

  if (ref.kind === "tag") {
    const canonicalId = deps.canonicalTagId ? deps.canonicalTagId(ref.id) : ref.id;
    const carrierIds = deps.referenceIndex ? projectReferences([canonicalId], deps.referenceIndex) : new Set<string>();
    const counts = new Map<string, number>();
    for (const carrierId of carrierIds) {
      const kind = deps.resolveRef(carrierId)?.kind ?? "other";
      counts.set(kind, (counts.get(kind) ?? 0) + 1);
    }
    const byKind = [...counts.entries()]
      .map(([kind, count]) => ({ kind, count }))
      .sort((a, b) => b.count - a.count);
    target.tag = { vocabularyLabel: typeLabel, carriers: carrierIds.size, byKind };
  }

  return target;
}
