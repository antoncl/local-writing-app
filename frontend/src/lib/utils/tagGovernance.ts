// The governance operations `TagRosterPopover` drives, injected per vocabulary
// (#247, slice 2 PR-3). The popover is one presentational surface over these —
// which API it talks to, and how it reconciles afterwards, is the adapter's job,
// not a `mode` branch inside the component (feedback_mode_is_presentation_not_functionality).
//
// Two vocabularies, two adapters: project tags (per-layer, scoped) and assistant
// tags (flat, machine-global, NO scope). `supportsScope` is the one presentation
// difference the popover reads — the assistant roster hides "Suggest on…" and its
// scope chips, because assistant tags have nothing to scope.

import { api } from "@/lib/api";
import { bumpTagVocabularyRevision, refreshKnownTags } from "@/lib/stores/tags";
import { refreshAssistantTags } from "@/lib/stores/assistantTags";
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

export const assistantTagGovernance: TagGovernanceAdapter = {
  supportsScope: false,
  async loadCounts() {
    const overview = await api.getAssistantTagsOverview();
    return new Map(overview.tags.map((tag) => [tag.name.toLowerCase(), tag.count]));
  },
  async setColor(name, color) {
    await api.setAssistantTagColor(name, color);
    await refreshAssistantTags();
  },
  async updateScope() {
    // Assistant tags have no scope; `supportsScope: false` keeps the popover
    // from ever reaching this. Guard loudly in case that invariant slips.
    throw new Error("Assistant tags have no scope.");
  },
  async merge(sources, target) {
    await api.mergeAssistantTags(sources, target);
  },
  async reconcile() {
    bumpTagVocabularyRevision();
  },
};
