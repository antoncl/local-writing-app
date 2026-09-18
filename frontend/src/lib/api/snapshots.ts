import type { LoreEntry, Snapshot, SnapshotDetail, SnapshotList } from "@/lib/types";
import { request } from "./core";

// Node-scoped snapshot routes (ADR-0087 / ADR-0088). The SAME store the scene
// routes in manuscript.ts serve, addressed by node id for any snapshot-eligible
// kind, with an optional authoring `layer` for a book override's history
// (ADR-0087 §3b). The on-card surface (ADR-0088) reaches these for a lore card;
// a manuscript scene keeps its own /scenes routes — they carry the entity-drift
// witness the node routes deliberately do not (ADR-0087 §5). `layer` is omitted
// from the query when null, which reads the base file's own history.

const NODE = (nodeId: string) => `/nodes/${encodeURIComponent(nodeId)}/snapshots`;

/** `.../snapshots/{id}<suffix>` with the optional `?layer=` appended AFTER the
 *  suffix, so `/restore`, `/pin`, `/description` keep the layer in the query. */
function item(nodeId: string, snapshotId: string, suffix: string, layer: string | null): string {
  const path = `${NODE(nodeId)}/${encodeURIComponent(snapshotId)}${suffix}`;
  return layer === null ? path : `${path}?layer=${encodeURIComponent(layer)}`;
}

function collection(nodeId: string, layer: string | null): string {
  const path = NODE(nodeId);
  return layer === null ? path : `${path}?layer=${encodeURIComponent(layer)}`;
}

export const snapshotsApi = {
  listNodeSnapshots(nodeId: string, layer: string | null = null) {
    return request<SnapshotList>(collection(nodeId, layer));
  },
  /** The camera for a non-scene node. Such a node carries no dynamic-context
   *  witness (ADR-0087 §5), so — unlike the scene camera — it sends no body. */
  captureNodeSnapshot(nodeId: string, layer: string | null = null) {
    return request<Snapshot>(collection(nodeId, layer), { method: "POST" });
  },
  readNodeSnapshot(nodeId: string, snapshotId: string, layer: string | null = null) {
    return request<SnapshotDetail>(item(nodeId, snapshotId, "", layer));
  },
  /** Capture-then-restore in one call — never a client-side pair, which can
   *  half-fail (#395). The route returns the re-folded node in its own shape;
   *  lore is the only kind the surface restores today (ADR-0088 S1), so it is
   *  typed `LoreEntry`. The caller only forwards it (a lore reload re-fetches by
   *  id), so the exact shape is not relied on here. */
  restoreNodeSnapshot(nodeId: string, snapshotId: string, layer: string | null = null) {
    return request<LoreEntry>(item(nodeId, snapshotId, "/restore", layer), { method: "POST" });
  },
  /** Pin an automatic snapshot: flip `retention` thinned → kept (ADR-0043
   *  Amendment 1). Idempotent. */
  pinNodeSnapshot(nodeId: string, snapshotId: string, layer: string | null = null) {
    return request<Snapshot>(item(nodeId, snapshotId, "/pin", layer), { method: "POST" });
  },
  /** Set (or clear, with `""`) the snapshot's one-line description (#468). */
  setNodeSnapshotDescription(
    nodeId: string,
    snapshotId: string,
    description: string,
    layer: string | null = null,
  ) {
    return request<Snapshot>(item(nodeId, snapshotId, "/description", layer), {
      method: "PUT",
      body: JSON.stringify({ description }),
    });
  },
  /** Delete one snapshot — the feature's only irreversible gesture. Returns what
   *  remains so the strip re-lists in one call. */
  deleteNodeSnapshot(nodeId: string, snapshotId: string, layer: string | null = null) {
    return request<SnapshotList>(item(nodeId, snapshotId, "", layer), { method: "DELETE" });
  },
};
