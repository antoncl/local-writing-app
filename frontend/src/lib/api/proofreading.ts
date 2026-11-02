// Proofreading (ADR-0102 §7): the lens reads and writes its words, rules and
// ignores only through these. Every write answers with the whole merged setup.
import type { ProofreadingDialect, ProofreadingSetup } from "@/lib/types";
import { request } from "./core";

const write = (path: string, method: "POST" | "PUT", body: unknown) =>
  request<ProofreadingSetup>(path, { method, body: JSON.stringify(body) });

export const proofreadingApi = {
  getProofreading() {
    return request<ProofreadingSetup>("/proofreading");
  },
  addProofreadingWord(word: string, layerId: string) {
    return write("/proofreading/words", "POST", { word, layer_id: layerId });
  },
  removeProofreadingWord(word: string, layerId: string) {
    return write("/proofreading/words/remove", "POST", { word, layer_id: layerId });
  },
  /** `enabled: null` sets the rule back to "as inherited" at that layer. */
  setProofreadingRule(rule: string, enabled: boolean | null, layerId: string) {
    return write("/proofreading/rules", "PUT", { rule, enabled, layer_id: layerId });
  },
  setProofreadingDialect(dialect: ProofreadingDialect | null, layerId: string) {
    return write("/proofreading/dialect", "PUT", { dialect, layer_id: layerId });
  },
  /** Every hash of the spot: one per lint there (`hashesOf`). */
  ignoreProofreadingSpot(nodeId: string, hashes: string[]) {
    return write("/proofreading/ignores", "POST", { node_id: nodeId, hashes });
  },
};
