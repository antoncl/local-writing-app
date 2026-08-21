// Pure presentation helpers for a document's editor shell (extracted from
// NodeEditor to keep that shell under the file-size guard, #1261): a document's
// effective body shape and its friendly kind label. No component state — both
// are functions of their argument, so they unit-test on their own and are shared
// by NodeEditor's derivations.
import type { BodyShape, EntryTypeDefinition } from "@/lib/types";

// Effective body shape for an entry type. Falls back through the legacy
// has_body / body_editor pair when body_shape is absent (existing on-disk
// schemas don't carry it). See decisions-node-editor-modularization +
// decisions-node-editor-body-spec.
export function deriveBodyShape(def: EntryTypeDefinition | null | undefined): BodyShape {
  if (def?.body_shape) return def.body_shape;
  if (def?.has_body === false) return "none";
  if (def?.body_editor === "code") return "code";
  return "prose";
}

// Friendly noun for a document kind — the type-header label ("<label> type"),
// the rail's aria-label, the title aria-labels. A map, not a scene-defaulting
// ternary, so every kind reads correctly: the plot kinds (card / plotline / arc
// / template) were all mislabelled "Scene type" (#737 follow-on).
const DOCUMENT_LABELS: Record<string, string> = {
  scene: "Scene",
  lore: "Entry",
  structure_node: "Node",
  chat: "Chat",
  research: "Note",
  prompt: "Prompt",
  assistant: "Assistant",
  view: "View",
  project: "Project",
  snippet: "Snippet",
  plot_card: "Card",
  plotline: "Plotline",
  plot_template: "Template",
};

export function documentLabelFor(documentKind: string): string {
  return DOCUMENT_LABELS[documentKind] ?? "Scene";
}
