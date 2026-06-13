export type StructureNode = {
  id: string;
  type: "root" | "act" | "chapter" | "sequence" | "scene";
  title: string;
  scene_id?: string | null;
  children: StructureNode[];
};

export type StructureDocument = {
  root: StructureNode;
};

export type Scene = {
  id: string;
  title: string;
  body_markdown: string;
  revision: string;
  status: string;
};

export type TodoItem = {
  id: string;
  text: string;
  status: "open" | "done";
  scope: "project" | "scene";
  scene_id?: string | null;
};

export type TodoDocument = {
  items: TodoItem[];
};

export type ProjectInfo = {
  title: string;
  root_path: string;
};

export type DirectoryEntry = {
  name: string;
  path: string;
};

export type DirectoryListing = {
  path: string;
  parent_path?: string | null;
  directories: DirectoryEntry[];
};

export type SearchHit = {
  file_id: string;
  path: string;
  line: number;
  excerpt: string;
};
