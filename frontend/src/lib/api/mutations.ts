import type { EffectiveStateResponse, MutationMarkerList, Scene } from "@/lib/types";
import { request } from "./core";

export const mutationsApi = {
  // Mid-scene lore mutations (#33). The timeline is the manuscript-ordered list
  // for a lore entity; effective state resolves its overrides at a (scene,
  // position) for the time-slider. NOTE: the editor rewrites/removes pills
  // directly in the ProseMirror doc + body save, so updateMutation/deleteMutation
  // below are currently unused by the app — they mirror the backend PATCH/DELETE
  // routes (exercised by backend tests) and are kept for parity / future callers.
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
    // `exclude` skips record ids — the list-edit authoring baseline when
    // re-editing a unit (#71, ADR-0017).
    const posQuery = pos === undefined ? "" : `&pos=${pos}`;
    const excludeQuery =
      exclude && exclude.length > 0 ? `&exclude=${encodeURIComponent(exclude.join(","))}` : "";
    return request<EffectiveStateResponse>(
      `/lore/${entityId}/effective?scene=${encodeURIComponent(sceneId)}${posQuery}${excludeQuery}`,
    );
  },
  updateMutation(sceneId: string, markerId: string, updates: { entity_id?: string; field?: string; value?: string }) {
    return request<Scene>(`/scenes/${sceneId}/mutations/${markerId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteMutation(sceneId: string, markerId: string) {
    return request<Scene>(`/scenes/${sceneId}/mutations/${markerId}`, {
      method: "DELETE",
    });
  },
};
