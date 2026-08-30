import type {
  LooseScene,
  Scene,
  Snapshot,
  SnapshotDetail,
  SnapshotDrift,
  SnapshotList,
  StructureDocument,
  StructureNodeDeletePreview,
} from "@/lib/types";
import { request } from "./core";

export const manuscriptApi = {
  getStructure() {
    return request<StructureDocument>("/structure");
  },
  createStructureNode(title: string, entryType: string, parentId?: string | null) {
    return request<StructureDocument>("/structure/nodes", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType, parent_id: parentId ?? null }),
    });
  },
  getLooseScenes() {
    // Scene files on disk no manuscript node references — the import offer,
    // read on its own now (#635) rather than off the validation report.
    return request<LooseScene[]>("/structure/loose-scenes");
  },
  importLooseScenes(sceneIds: string[]) {
    return request<StructureDocument>("/structure/import-loose", {
      method: "POST",
      body: JSON.stringify({ scene_ids: sceneIds }),
    });
  },
  renameStructureNode(nodeId: string, title: string) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },
  moveStructureNode(nodeId: string, targetParentId: string, position: number) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}/move`, {
      method: "POST",
      body: JSON.stringify({ target_parent_id: targetParentId, position }),
    });
  },
  cascadeDeletePreview(nodeId: string) {
    return request<StructureNodeDeletePreview>(`/structure/nodes/${encodeURIComponent(nodeId)}/cascade-preview`);
  },
  deleteStructureNode(nodeId: string) {
    return request<StructureDocument>(`/structure/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  },
  createScene(title: string, parentId?: string) {
    return request<Scene>("/scenes", {
      method: "POST",
      body: JSON.stringify({ title, parent_id: parentId }),
    });
  },
  getScene(sceneId: string) {
    return request<Scene>(`/scenes/${sceneId}`);
  },
  /** `dynamicContext` is the set of lore entries the prose editor detected in
   *  this body (#439). Read only by the automatic snapshot capture inside the
   *  save; omitted when no prose editor reported, which the backend treats as
   *  *not observed* rather than as empty. */
  saveScene(scene: Scene, body: string, dynamicContext?: string[]) {
    return request<Scene>(`/scenes/${scene.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: scene.title,
        body,
        base_revision: scene.revision,
        status: scene.status,
        entry_type: scene.entry_type,
        metadata: scene.metadata,
        ...(dynamicContext ? { dynamic_context: dynamicContext } : {}),
      }),
    });
  },
  deleteScene(sceneId: string) {
    return request<StructureDocument>(`/scenes/${sceneId}`, {
      method: "DELETE",
    });
  },
  // ---- scene snapshots (ADR-0043 / ADR-0044, #401) -------------------------
  listSnapshots(sceneId: string) {
    return request<SnapshotList>(`/scenes/${encodeURIComponent(sceneId)}/snapshots`);
  },
  /** The camera: an explicit, never-thinned capture. Carries the dynamic
   *  context so an author-invoked snapshot witnesses the same world an
   *  automatic one does. */
  captureSnapshot(sceneId: string, dynamicContext?: string[]) {
    return request<Snapshot>(`/scenes/${encodeURIComponent(sceneId)}/snapshots`, {
      method: "POST",
      ...(dynamicContext ? { body: JSON.stringify({ dynamic_context: dynamicContext }) } : {}),
    });
  },
  readSnapshot(sceneId: string, snapshotId: string) {
    return request<SnapshotDetail>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}`,
    );
  },
  /** The drift report alone (#583). Once the content diff (runs + fields + title)
   *  is computed client-side, this is the one half that stays on the server —
   *  the "now" witness needs resolved entity state — so it gets a slim call
   *  carrying the dynamic context the editor observed plus the scene's unsaved
   *  buffer (`metadata` + `body`, #581), so the now-witness resolves the same
   *  "now" the client-side field flip does instead of the ~6 s-stale disk copy.
   *  `null` dynamic context is "not observed", `[]` is "observed and empty" —
   *  the distinction the service turns on (#439). */
  snapshotDrift(
    sceneId: string,
    snapshotId: string,
    dynamicContext: string[] | null,
    metadata: Record<string, unknown>,
    body: string,
  ) {
    return request<SnapshotDrift>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/drift`,
      {
        method: "POST",
        body: JSON.stringify({ dynamic_context: dynamicContext, metadata, body }),
      },
    );
  },
  /** Captures the current state and restores, in ONE call. Never do this as a
   *  client-side capture-then-restore: the pair can half-fail into a snapshot
   *  nobody asked for and an author who cannot tell whether it worked (#395). */
  restoreSnapshot(sceneId: string, snapshotId: string) {
    return request<Scene>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/restore`,
      { method: "POST" },
    );
  },
  /** Finalize a roleplay scene (ADR-0070 S3): capture a `kept` safety-net
   *  snapshot, then replace the body with the AI-produced clean prose — in ONE
   *  call, the same #395 reason `restoreSnapshot` is (a client-side
   *  capture-then-write can half-fail). The AI generation ran beforehand through
   *  the ordinary generate path, so the finalize prompt stays author-
   *  customizable; this only commits the reviewed result. */
  finalizeScene(sceneId: string, body: string, dynamicContext?: string[]) {
    return request<Scene>(`/scenes/${encodeURIComponent(sceneId)}/finalize`, {
      method: "POST",
      body: JSON.stringify({ body, ...(dynamicContext ? { dynamic_context: dynamicContext } : {}) }),
    });
  },
  /** Pin an automatic snapshot: flip `retention` from thinned to kept so it
   *  survives thinning without re-capturing it (ADR-0043 Amendment 1).
   *  Idempotent — pinning an already-kept snapshot returns it unchanged. */
  pinSnapshot(sceneId: string, snapshotId: string) {
    return request<Snapshot>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/pin`,
      { method: "POST" },
    );
  },
  /** Set (or clear, with `""`) the snapshot's one-line description (#468).
   *  Writes the sidecar's authorial half only — the body and witness are
   *  frozen. */
  setSnapshotDescription(sceneId: string, snapshotId: string, description: string) {
    return request<Snapshot>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}/description`,
      { method: "PUT", body: JSON.stringify({ description }) },
    );
  },
  /** Delete one snapshot — the feature's only irreversible gesture, which is
   *  why the surface confirms it (ADR-0043). Returns what remains, so the strip
   *  re-lists in one call. */
  deleteSnapshot(sceneId: string, snapshotId: string) {
    return request<SnapshotList>(
      `/scenes/${encodeURIComponent(sceneId)}/snapshots/${encodeURIComponent(snapshotId)}`,
      { method: "DELETE" },
    );
  },
};
