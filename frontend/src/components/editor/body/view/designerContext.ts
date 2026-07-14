// Shared context between the view designer shell (ViewBodyView) and its custom
// Svelte Flow nodes (ViewFlowNode). Set once by the shell as a getter so the
// nodes always read fresh reactive state (schema-derived options, data sources,
// and the node-mutation callbacks). 0.5.0 step 3, #80.

import { getContext, setContext } from "svelte";
import type { ViewNodeData } from "@/lib/views/viewGraph";
import type {
  AssistantEntrySummary,
  LoreEntrySummary,
  MetadataFieldDefinition,
  PromptEntrySummary,
  ScopedTag,
  StructureDocument,
} from "@/lib/types";

export type EntryTypeOption = { fqn: string; name: string };
export type FieldOption = { key: string; name: string; def: MetadataFieldDefinition };
export type SavedViewOption = { id: string; title: string };

export type DesignerContext = {
  // node mutation, wired back to the shell's bound Svelte Flow arrays
  updateNodeData: (id: string, patch: Partial<ViewNodeData>) => void;
  removeNode: (id: string) => void;
  // Which node is expanded to its full editor (§A, #220). A node's header is a
  // toggle (`toggleExpanded`); a canvas-background click clears it. Independent
  // of Svelte Flow selection, so clicking a header a second time collapses.
  expandedId: string | null;
  toggleExpanded: (nodeId: string) => void;
  // schema-derived leaf-config options for the view's anchor kind
  kind: string;
  entryTypes: EntryTypeOption[];
  // `fields` = the anchor-kind roster (fallback / non-node-specific reads).
  // `fieldsFor(nodeId)` = the roster for that node's INPUT-set kind (ADR-0031 §F,
  // kind-level) — the pickers use it so a node downstream of a cross-kind
  // `field_of` offers the projected kind's fields, not the view anchor's.
  fields: FieldOption[];
  fieldsFor: (nodeId: string) => FieldOption[];
  fieldByKey: (key: string) => MetadataFieldDefinition | null;
  // Whether a node's value slot (#196) is fed by a wired source edge — the node
  // renders the wired state instead of an inline literal / promote control.
  valueWired: (nodeId: string) => boolean;
  // Whether a specific handle (by id) on a node currently has an edge, so a wired
  // port stays filled at rest — not only while hovered (§240).
  handleConnected: (nodeId: string, handleId: string) => boolean;
  // `tags` = flat tag strings present in this kind's universe (feeds the `tagged`
  // leaf `<select>`). `knownTags` = the project's scoped roster (feeds the
  // FieldValueEditor → TagPicker "+" for `tags`-type field values, #243).
  tags: string[];
  knownTags: ScopedTag[];
  savedViews: SavedViewOption[];
  // data sources for the hand_picked NodePicker + FieldValueEditor pickers
  loreEntries: LoreEntrySummary[];
  promptEntries: PromptEntrySummary[];
  assistantEntries: AssistantEntrySummary[];
  structure: StructureDocument | null;
  researchStructure: StructureDocument | null;
};

const KEY = Symbol("view-designer-context");

export function setDesignerContext(getter: () => DesignerContext): void {
  setContext(KEY, getter);
}

export function useDesignerContext(): () => DesignerContext {
  return getContext<() => DesignerContext>(KEY);
}
