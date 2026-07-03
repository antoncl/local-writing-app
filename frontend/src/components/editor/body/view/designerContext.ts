// Shared context between the view designer shell (ViewBodyView) and its custom
// Svelte Flow nodes (ViewFlowNode). Set once by the shell as a getter so the
// nodes always read fresh reactive state (schema-derived options, data sources,
// and the node-mutation callbacks). 0.5.0 step 3, #80.

import { getContext, setContext } from "svelte";
import type { ViewNodeData } from "@/lib/views/viewGraph";
import type {
  LoreEntrySummary,
  MetadataFieldDefinition,
  PromptEntrySummary,
  StructureDocument,
} from "@/lib/types";

export type EntryTypeOption = { fqn: string; name: string };
export type FieldOption = { key: string; name: string; def: MetadataFieldDefinition };
export type SavedViewOption = { id: string; title: string };

export type DesignerContext = {
  // node mutation, wired back to the shell's bound Svelte Flow arrays
  updateNodeData: (id: string, patch: Partial<ViewNodeData>) => void;
  removeNode: (id: string) => void;
  // schema-derived leaf-config options for the view's anchor kind
  kind: string;
  entryTypes: EntryTypeOption[];
  fields: FieldOption[];
  fieldByKey: (key: string) => MetadataFieldDefinition | null;
  tags: string[];
  savedViews: SavedViewOption[];
  // data sources for the hand_picked NodePicker + FieldValueEditor pickers
  loreEntries: LoreEntrySummary[];
  promptEntries: PromptEntrySummary[];
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
