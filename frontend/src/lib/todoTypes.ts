// Todo wire types. Extracted from types.ts to keep that barrel under the
// file-size cap; re-exported from `@/lib/types` so it stays the single import
// surface.

import type { ChangeCandidateRoute } from "./propagationTypes";

/** ADR-0090 §3: where a review item's change came from — the source entry,
 *  the baseline it was measured from (`""` = the whole entry, not a
 *  snapshot), the route of the candidate's first reason, and — only when
 *  that reason is `mutates_source` — the marker it names. */
export type TodoSource = {
  node_id: string;
  snapshot_id: string;
  reason: ChangeCandidateRoute;
  marker_id: string;
};

export type TodoItem = {
  id: string;
  text: string;
  status: "open" | "done";
  scope: "project" | "scene" | "node";
  scene_id?: string | null;
  anchor_id?: string | null;
  // ADR-0090 §3: a `node`-scoped item's dependent, and the source block a
  // review item the app wrote carries (absent on a writer-authored todo).
  node_id?: string | null;
  source?: TodoSource | null;
};

export type TodoDocument = {
  items: TodoItem[];
};

// An in-prose embedded TODO, enumerated by scanning scene bodies (GH #45).
// Editor-pane independent — a rebuildable index over scenes.
export type EmbeddedTodoRecord = {
  todo_id: string;
  scene_id: string;
  status: "open" | "done";
  note: string;
  text: string;
  line: number;
  scene_path: string;
};

export type EmbeddedTodoList = {
  items: EmbeddedTodoRecord[];
};
