// Pure presentation helpers for a document's editor shell (extracted from
// NodeEditor to keep that shell under the file-size guard, #1261): a document's
// effective body shape and its friendly kind label. No component state — both
// are functions of their argument, so they unit-test on their own and are shared
// by NodeEditor's derivations.
import type { BodyShape, EntryTypeDefinition, MetadataSchema } from "@/lib/types";

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
  plot_deck: "Deck",
  plot_template: "Template",
  tag: "Tag",
};

export function documentLabelFor(documentKind: string): string {
  return DOCUMENT_LABELS[documentKind] ?? "Scene";
}

// structure_node has no schema kind of its own — Acts/Chapters share
// kind="manuscript" in the metadata schema. Reuse the manuscript entry types so
// the type selector still lists Act/Chapter/Scene/etc.
// The entry-type control's options. For most kinds `documentKind` IS the schema
// kind, so we list that kind's concrete sub-types (a switchable variant set —
// prompt:base ↔ prompt:roleplay). Two kinds don't line up 1:1: `structure_node`
// is a scene, and `plot_template`'s schema kind is `plot` — but plot's other
// entry_types (plotline, board) are DISTINCT node classes, not interchangeable
// variants, so a template offers only its own type (never a reclassify), and
// showing it also fixes the otherwise-blank select (S4c finding #2).
// The plot document kinds are synthetic shapes whose schema `kind` is "plot", not
// their documentKind — so the kind-filter below finds nothing and the type select
// falls back to the raw entry_type id ("plot:template_instance") instead of a name.
// List just the node's own type: the plot classes (card / template / plotline / deck) are
// distinct, so a cross-class reclassify is never offered (the #720 call, now
// generalized past plot_template). A plotline is edited on its board node by default,
// but can also be opened in a full pane (ADR-0053 §3, the escape hatch) — same rule.
const OWN_TYPE_ONLY = new Set(["plot_template", "plot_card", "plotline", "plot_deck"]);

export function entryTypesForDocument(
  schema: MetadataSchema | null | undefined,
  documentKind: string,
  entryType: string,
): [string, EntryTypeDefinition][] {
  const all = Object.entries(schema?.entry_types ?? {});
  return OWN_TYPE_ONLY.has(documentKind)
    ? all.filter(([typeId]) => typeId === entryType)
    : all.filter(
        ([, definition]) => definition.kind === (documentKind === "structure_node" ? "manuscript" : documentKind) && !definition.abstract,
      );
}
