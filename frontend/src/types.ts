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
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
};

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export type EntryMetadata = Record<string, MetadataValue>;

export type MetadataFieldType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "date"
  | "select"
  | "multi_select"
  | "entity_ref"
  | "entity_ref_list"
  | "tags"
  | "computed";

export type MetadataFieldDefinition = {
  name: string;
  type: MetadataFieldType;
  options: string[];
  target?: Record<string, string> | null;
  computed?: Record<string, string> | null;
};

export type EntryTypeDefinition = {
  name: string;
  kind: string;
  parent?: string | null;
  fields: string[];
};

export type MetadataSchema = {
  version: number;
  entry_types: Record<string, EntryTypeDefinition>;
  fields: Record<string, MetadataFieldDefinition>;
};

export type MetadataSchemaLayer = {
  id: string;
  label: string;
  folder_path: string;
  schema_path: string;
  exists: boolean;
};

export type MetadataSchemaLayers = {
  layers: MetadataSchemaLayer[];
};

export type MetadataDefinitionSource = {
  layer_id: string;
  layer_label: string;
  schema_path?: string | null;
  built_in: boolean;
};

export type MetadataSchemaOverview = {
  effective_schema: MetadataSchema;
  layers: MetadataSchemaLayer[];
  entry_type_sources: Record<string, MetadataDefinitionSource>;
  field_sources: Record<string, MetadataDefinitionSource>;
};

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

export type ProjectValidation = {
  valid: boolean;
  warnings: string[];
  errors: string[];
};

export type ProjectInfo = {
  title: string;
  root_path: string;
  projects_base_folder?: string | null;
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
  todo_id?: string | null;
};
