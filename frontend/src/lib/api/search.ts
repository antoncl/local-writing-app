import type {
  ReferenceCandidatesResponse,
  ReferenceGraphResponse,
  ReferenceResolveResponse,
  ReplaceHitRef,
  ReplaceResponse,
  SearchHit,
} from "@/lib/types";
import { request } from "./core";

export type SearchParams = {
  query: string;
  match_case?: boolean;
  whole_word?: boolean;
  kinds?: string[] | null;
  include_open_todos?: boolean;
};

export type ReplaceParams = {
  replacement: string;
  hits: ReplaceHitRef[];
};

export const searchApi = {
  search(params: SearchParams) {
    return request<{ query: string; hits: SearchHit[] }>("/search", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },
  // ADR-0085 §4: one write per hit's node, through that node's own save — this
  // endpoint is the whole mechanism, always 200 with a per-hit outcome.
  replace(params: ReplaceParams) {
    return request<ReplaceResponse>("/search/replace", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },
  resolveReferences(ids: string[]) {
    return request<ReferenceResolveResponse>("/references/resolve", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },
  listReferenceCandidates(filters: { kind?: string; entry_type?: string; exclude_id?: string } = {}) {
    const params = new URLSearchParams();
    if (filters.kind) params.set("kind", filters.kind);
    if (filters.entry_type) params.set("entry_type", filters.entry_type);
    if (filters.exclude_id) params.set("exclude_id", filters.exclude_id);
    const query = params.toString();
    return request<ReferenceCandidatesResponse>(`/references/candidates${query ? `?${query}` : ""}`);
  },
  referenceGraph() {
    return request<ReferenceGraphResponse>("/references/graph");
  },
};
