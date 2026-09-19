// Shared id → node hydration for reference fields (#2010 lift of
// ReferencePicker's `resolveRefById`). Pure — no Svelte imports — so a caller
// (a `$derived` in ReferencePicker, ReferenceListTab, MetadataPanel's list-
// index summary) rebuilds one resolver function from the in-memory data
// sources it already holds, and every reference-rendering surface shares this
// one walk instead of re-deriving its own.
//
// Returns `null` for an id none of the indices resolve — a caller decides
// what "missing" renders as (ReferencePicker's danger-tinted pill vs.
// ReferenceListTab's "Missing" row), so this module carries no sentinel /
// fallback-kind opinion of its own.
import { canonicalIdIn } from "@/lib/stores/tagNodes";
import type {
  AssistantEntrySummary,
  EntryMetadata,
  LoreEntrySummary,
  PromptEntrySummary,
  StructureDocument,
  StructureNode,
  TagEntry,
} from "@/lib/types";

export type ResolvedRef = {
  id: string;
  // A strict subset of NodePickerRef["kind"] — every kind this module can
  // actually resolve to. Callers that need the full NodePickerRef union (a
  // picker's own "missing" fallback) widen it themselves.
  kind: "manuscript" | "lore" | "snippet" | "assistant" | "plot" | "tag";
  title: string;
  entry_type?: string;
  // Full instance metadata, when the source roster carries it (lore/prompt/
  // assistant/tag) — #2011's peek card needs it for summaryValues(). Plot
  // stays without (its roster carries no metadata); a scene's is the
  // StructureNode's own front matter.
  metadata?: EntryMetadata;
};

export type RefResolveDeps = {
  structure?: StructureDocument | null;
  loreEntries?: LoreEntrySummary[];
  promptEntries?: PromptEntrySummary[];
  assistantEntries?: AssistantEntrySummary[];
  plotEntries?: { id: string; title: string; entry_type: string }[];
  // Full tag entries (entry_type included) — pass the `$tagById` store snapshot
  // for a caller that needs a tag ref's real entry_type (a picker's type pill).
  tagById?: ReadonlyMap<string, TagEntry>;
  // Title-only fallback for a caller with no tag roster threaded (e.g. a body
  // tab that only needs *something* to show, not the tag's vocabulary type).
  // Ignored when `tagById` is also given.
  tagTitleById?: ReadonlyMap<string, string>;
};

function flattenScenesAll(
  node: StructureNode | null | undefined,
): Map<string, { id: string; title: string; entry_type: string; metadata?: EntryMetadata }> {
  const out = new Map<string, { id: string; title: string; entry_type: string; metadata?: EntryMetadata }>();
  const walk = (n: StructureNode) => {
    if (n.type === "manuscript:scene" && n.scene_id) {
      const entryType = (n as unknown as { entry_type?: string }).entry_type ?? "manuscript:scene";
      out.set(n.scene_id, { id: n.scene_id, title: n.title, entry_type: entryType, metadata: n.metadata ?? undefined });
    }
    for (const child of n.children ?? []) walk(child);
  };
  if (node) walk(node);
  return out;
}

/** Build one id → node resolver from the in-memory data sources a host holds.
 *  Rebuild it (a `$derived`) whenever those sources change — this module has
 *  no state of its own, so nothing here is reactive on its own. */
export function buildRefResolver(deps: RefResolveDeps): (id: string) => ResolvedRef | null {
  const sceneIndex = flattenScenesAll(deps.structure?.root);
  const loreIndex = new Map((deps.loreEntries ?? []).map((e) => [e.id, e] as const));
  const promptIndex = new Map((deps.promptEntries ?? []).map((e) => [e.id, e] as const));
  const assistantIndex = new Map((deps.assistantEntries ?? []).map((e) => [e.id, e] as const));
  const plotIndex = new Map((deps.plotEntries ?? []).map((e) => [e.id, e] as const));

  return (id: string): ResolvedRef | null => {
    const scene = sceneIndex.get(id);
    if (scene) return { id, kind: "manuscript", title: scene.title, entry_type: scene.entry_type, metadata: scene.metadata };
    const lore = loreIndex.get(id);
    if (lore) return { id, kind: "lore", title: lore.title, entry_type: lore.entry_type, metadata: lore.metadata };
    const snippet = promptIndex.get(id);
    if (snippet) return { id, kind: "snippet", title: snippet.title, entry_type: snippet.entry_type, metadata: snippet.metadata };
    const assistant = assistantIndex.get(id);
    if (assistant) return { id, kind: "assistant", title: assistant.title, entry_type: assistant.entry_type, metadata: assistant.metadata };
    const plotline = plotIndex.get(id);
    if (plotline) return { id, kind: "plot", title: plotline.title, entry_type: plotline.entry_type };
    if (deps.tagById) {
      const tag = deps.tagById.get(canonicalIdIn(deps.tagById, id));
      if (tag) return { id, kind: "tag", title: tag.title, entry_type: tag.entry_type, metadata: tag.metadata };
    } else if (deps.tagTitleById?.has(id)) {
      return { id, kind: "tag", title: deps.tagTitleById.get(id)! };
    }
    return null;
  };
}
