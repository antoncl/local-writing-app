// The governance operations `TagRosterPopover` drives, injected per vocabulary
// (#247, slice 2 PR-3). The popover is one presentational surface over these —
// which API it talks to, and how it reconciles afterwards, is the adapter's job,
// not a `mode` branch inside the component (feedback_mode_is_presentation_not_functionality).
//
// Project tags (per-layer, scoped) is the one vocabulary left here — the
// assistant-tag adapter retired with the legacy `assistant-tags.yaml` registry
// (ADR-0082 slice 2b): the assistant vocabulary is now `tag:assistant_tag`
// nodes, governed like any other tag node. `supportsScope` stays on the
// interface for a future second adapter over a scoped vocabulary.

import { api } from "@/lib/api";
import { bumpTagVocabularyRevision, refreshKnownTags } from "@/lib/stores/tags";
import type { NodePickerConfig } from "@/lib/types";

export interface TagGovernanceAdapter {
  /** Whether tags in this vocabulary carry a scope ("Suggest on…"). */
  readonly supportsScope: boolean;
  /** Use-counts keyed lowercase — row counts + the merge rewrite total. */
  loadCounts(): Promise<Map<string, number>>;
  /** Set/clear a tag's colour AND refresh the roster so chips recolour. A
   *  colour change rewrites no documents, so it uses the light roster refresh,
   *  never the full reconcile (matches PR-2's project-tag behaviour). */
  setColor(name: string, color: string | null): Promise<void>;
  /** Edit a tag's scope. Never called when `supportsScope` is false. */
  updateScope(name: string, scope: NodePickerConfig): Promise<void>;
  /** Fold `sources` into `target` (rename = a single source). */
  merge(sources: string[], target: string): Promise<void>;
  /** Reconcile after a rename/merge/scope rewrote documents on disk. Both
   *  adapters bump the one vocabulary-revision signal App reconciles off —
   *  App's `refreshAfterTagChange` re-syncs both vocabularies' rosters, the
   *  entry lists, and open-editor baselines so an open editor can't clobber the
   *  rewrite on its next save. */
  reconcile(): Promise<void>;
}

export const projectTagGovernance: TagGovernanceAdapter = {
  supportsScope: true,
  async loadCounts() {
    const overview = await api.getTagsOverview();
    return new Map(overview.tags.map((tag) => [tag.name.toLowerCase(), tag.count]));
  },
  async setColor(name, color) {
    await api.setTagColor(name, color);
    await refreshKnownTags();
  },
  async updateScope(name, scope) {
    await api.updateTagScope(name, scope);
  },
  async merge(sources, target) {
    await api.mergeTags(sources, target);
  },
  async reconcile() {
    bumpTagVocabularyRevision();
  },
};
