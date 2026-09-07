// Todo wire types. Extracted from types.ts to keep that barrel under the
// file-size cap; re-exported from `@/lib/types` so it stays the single import
// surface.

export type TodoItem = {
  id: string;
  text: string;
  status: "open" | "done";
  scope: "project" | "scene";
  scene_id?: string | null;
  anchor_id?: string | null;
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
