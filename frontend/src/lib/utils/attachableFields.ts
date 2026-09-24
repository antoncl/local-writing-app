// The "+ Existing field" candidate list (#2180): fields a type does NOT
// already carry, but could ATTACH without creating a new shared definition —
// the frontend twin of the backend's `attach_metadata_field` visibility rule
// (`backend/app/services/project/schema_groups.py`).

import { computedFunctionChoice } from "./schemaTypeHelpers";
import type { MetadataFieldDefinition, MetadataSchemaOverview } from "@/lib/types";

// A field is attachable at `layerId` for `entryTypeId` when it is: not
// already a member of the type; not intrinsic (the resolver injects those
// into every type already); not a group-generated field (`group_origin` —
// those come from an L2 group application, not the flat field roster); not a
// built-in (non-authorable) computed field — those are resolver/panel-supplied
// and would be silently always-empty on another type; and DEFINED at or above
// `layerId` in the layer chain (its source is built-in, or its layer's rank
// is no farther from the base than `layerId`'s).
//
// Curation on top of the backend rule: a BUILT-IN field is offered only when a
// type of the same kind already carries it. Without that, a Scene would be
// offered every system field (`ai_model`, `source_template_id`, …) — legal,
// but noise nobody means to reuse. Fields the author defined are always
// offered, whatever kind they started on.
export function attachableFields(
  overview: MetadataSchemaOverview,
  entryTypeId: string,
  layerId: string,
): [string, MetadataFieldDefinition][] {
  const entryType = overview.effective_schema.entry_types[entryTypeId];
  if (!entryType) return [];
  const currentMembers = new Set(entryType.fields ?? []);
  const sameKindFields = new Set(
    Object.values(overview.effective_schema.entry_types)
      .filter((type) => type.kind === entryType.kind)
      .flatMap((type) => type.fields ?? []),
  );

  // `overview.layers` walks outermost (farthest ancestor) first, nearest
  // (the open project) last — so a layer at or before `layerId`'s index is
  // visible to it (`services/project/layers.py::_layer_sequence`).
  const layerIndex = overview.layers.findIndex((layer) => layer.id === layerId);
  const targetRank = layerIndex === -1 ? overview.layers.length - 1 : layerIndex;

  const visible = (fieldId: string): boolean => {
    const source = overview.field_sources[fieldId];
    if (!source) return false;
    if (source.built_in) return sameKindFields.has(fieldId);
    const sourceIndex = overview.layers.findIndex((layer) => layer.id === source.layer_id);
    return sourceIndex !== -1 && sourceIndex <= targetRank;
  };

  const out: [string, MetadataFieldDefinition][] = [];
  for (const [fieldId, field] of Object.entries(overview.effective_schema.fields)) {
    if (currentMembers.has(fieldId)) continue;
    if (field.intrinsic || field.category === "intrinsic") continue;
    if (field.group_origin) continue;
    if (field.type === "computed" && !computedFunctionChoice(field.computed?.function ?? "")) continue;
    if (!visible(fieldId)) continue;
    out.push([fieldId, field]);
  }
  out.sort(([, a], [, b]) => a.name.localeCompare(b.name));
  return out;
}
