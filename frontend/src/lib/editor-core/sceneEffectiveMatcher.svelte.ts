// Reactive scene-local effective-name matcher (#61), extracted from
// ProseBodyView to keep that component under the file-size cap. Given accessors
// for the open scene id, lore set and schema, it fetches the scene's effective
// name-set (`GET /api/scenes/{id}/effective-names`) and compiles a matcher that
// highlights entities under their *as-of-scene* names — so a mid-story rename is
// detected under its effective name in that scene's prose.
//
// Returns null while loading / when there's no scene, so the caller falls back
// to the global base-name matcher. Recomputes when any accessor changes (scene
// switch, lore edit via `invalidateOn`); live mutation-edit invalidation arrives
// with the #63 mutations-version signal.
import { api } from "@/lib/api";
import { compileMatcher, type CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

export function createSceneEffectiveMatcher(opts: {
  sceneId: () => string | null;
  entries: () => LoreEntrySummary[];
  schema: () => MetadataSchema | null;
  /** Called for its reactive reads only — recompute when it changes (e.g. the
   *  global matcher reference, which changes when lore is added/edited). */
  invalidateOn?: () => unknown;
}): { readonly current: CompiledMatcher | null } {
  let matcher = $state<CompiledMatcher | null>(null);
  $effect(() => {
    const sceneId = opts.sceneId();
    const entries = opts.entries();
    const schema = opts.schema();
    opts.invalidateOn?.();
    if (!sceneId) {
      matcher = null;
      return;
    }
    let cancelled = false;
    api
      .getSceneEffectiveNames(sceneId)
      .then((names) => {
        if (!cancelled) matcher = compileMatcher(entries, schema, names);
      })
      .catch(() => {
        if (!cancelled) matcher = null;
      });
    return () => {
      cancelled = true;
    };
  });
  return {
    get current() {
      return matcher;
    },
  };
}
