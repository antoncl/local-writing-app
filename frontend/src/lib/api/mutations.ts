import type { EffectiveStateResponse, MutationMarkerList } from "@/lib/types";
import { request } from "./core";

export const mutationsApi = {
  // Mid-scene lore mutations (#33). The timeline is the manuscript-ordered list
  // for a lore entity; effective state resolves its overrides at a (scene,
  // position) for the time-slider.
  getEntityMutations(entityId: string) {
    return request<MutationMarkerList>(`/lore/${entityId}/mutations`);
  },
  // Each lore entry's effective name-set (title + aliases) as of a scene — the
  // source for the effective-name-aware implicit-context matcher (#61).
  getSceneEffectiveNames(sceneId: string) {
    return request<Record<string, string[]>>(`/scenes/${encodeURIComponent(sceneId)}/effective-names`);
  },
  // The entity's records still open (live, not yet closed) at (scene, pos) — the
  // source for the `/mutate close` picker (#59).
  getLiveEntityMutations(entityId: string, sceneId: string, pos?: number) {
    const query = pos === undefined ? "" : `&pos=${pos}`;
    return request<MutationMarkerList>(
      `/lore/${entityId}/live-mutations?scene=${encodeURIComponent(sceneId)}${query}`,
    );
  },
  getEntityEffectiveState(entityId: string, sceneId: string, pos?: number, exclude?: string[]) {
    // `exclude` skips anchor ids (ADR-0095 §3) — the list-edit authoring
    // baseline when re-editing a unit (#71, ADR-0017).
    const posQuery = pos === undefined ? "" : `&pos=${pos}`;
    const excludeQuery =
      exclude && exclude.length > 0 ? `&exclude=${encodeURIComponent(exclude.join(","))}` : "";
    return request<EffectiveStateResponse>(
      `/lore/${entityId}/effective?scene=${encodeURIComponent(sceneId)}${posQuery}${excludeQuery}`,
    );
  },
  // ADR-0095: updateMutation/deleteMutation/rewriteMutationUnit retired with
  // their backend routes — editing now saves the mutation SET (mutationSetsApi),
  // never the scene. See mutationSetsApi.copyMutationSet for the one new route.
};
