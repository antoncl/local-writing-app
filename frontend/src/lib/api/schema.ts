import type {
  AssistantTagList,
  AssistantTagsOverview,
  EntryTypeDefinition,
  GroupApplication,
  KnownTags,
  NodePickerConfig,
  TagsOverview,
  MetadataFieldDefinition,
  MetadataGroupDefinition,
  MetadataSchema,
  MetadataSchemaLayers,
  MetadataSchemaOverview,
} from "@/lib/types";
import { request } from "./core";

export const schemaApi = {
  getMetadataSchema() {
    return request<MetadataSchema>("/metadata/schema");
  },
  getMetadataSchemaLayers() {
    return request<MetadataSchemaLayers>("/metadata/schema/layers");
  },
  getMetadataSchemaOverview() {
    return request<MetadataSchemaOverview>("/metadata/schema/overview");
  },
  getKnownTags() {
    return request<KnownTags>("/tags");
  },
  getAssistantTags() {
    return request<AssistantTagList>("/assistant-tags");
  },
  setAssistantTagColor(name: string, color: string | null) {
    return request<AssistantTagList>(`/assistant-tags/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ color }),
    });
  },
  getAssistantTagsOverview() {
    return request<AssistantTagsOverview>("/assistant-tags/overview");
  },
  mergeAssistantTags(sources: string[], target: string) {
    // Rename is a single-source merge, exactly like mergeTags (#247).
    return request<AssistantTagList>("/assistant-tags/merge", {
      method: "POST",
      body: JSON.stringify({ sources, target }),
    });
  },
  getTagsOverview() {
    return request<TagsOverview>("/tags/overview");
  },
  updateTagScope(name: string, scope: NodePickerConfig) {
    return request<KnownTags>("/tags/scope", {
      method: "PUT",
      body: JSON.stringify({ name, scope }),
    });
  },
  setTagColor(name: string, color: string | null) {
    return request<KnownTags>("/tags/color", {
      method: "PUT",
      body: JSON.stringify({ name, color }),
    });
  },
  mergeTags(sources: string[], target: string) {
    return request<KnownTags>("/tags/merge", {
      method: "POST",
      body: JSON.stringify({ sources, target }),
    });
  },
  upsertMetadataEntryType(layerId: string, entryTypeId: string, entryType: EntryTypeDefinition, allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, entry_type: entryType, allow_existing: allowExisting }),
    });
  },
  deleteMetadataEntryType(entryTypeId: string) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "DELETE",
      body: JSON.stringify({ entry_type_id: entryTypeId }),
    });
  },
  upsertMetadataField(layerId: string, fieldId: string, field: MetadataFieldDefinition, entryType = "manuscript:scene", allowExisting = true, optionMigration: Record<string, string> | null = null) {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, field_id: fieldId, field, entry_type: entryType, allow_existing: allowExisting, option_migration: optionMigration }),
    });
  },
  moveMetadataField(fieldId: string, targetLayerId: string, entryType = "manuscript:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/move", {
      method: "POST",
      body: JSON.stringify({ field_id: fieldId, target_layer_id: targetLayerId, entry_type: entryType }),
    });
  },
  renameMetadataField(oldFieldId: string, newFieldId: string, entryType = "manuscript:scene") {
    return request<MetadataSchema>("/metadata/schema/fields/rename", {
      method: "POST",
      body: JSON.stringify({ old_field_id: oldFieldId, new_field_id: newFieldId, entry_type: entryType }),
    });
  },
  deleteMetadataField(fieldId: string, entryType = "manuscript:scene") {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "DELETE",
      body: JSON.stringify({ field_id: fieldId, entry_type: entryType }),
    });
  },
  upsertMetadataGroup(layerId: string, groupId: string, group: MetadataGroupDefinition, allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/groups", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, group_id: groupId, group, allow_existing: allowExisting }),
    });
  },
  deleteMetadataGroup(groupId: string) {
    return request<MetadataSchema>("/metadata/schema/groups", {
      method: "DELETE",
      body: JSON.stringify({ group_id: groupId }),
    });
  },
  setEntryTypeGroupApplications(layerId: string, entryTypeId: string, applications: GroupApplication[]) {
    return request<MetadataSchema>("/metadata/schema/entry-types/group-applications", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, applications }),
    });
  },
  setEntryTypeFieldOrder(layerId: string, entryTypeId: string, fieldOrder: string[]) {
    return request<MetadataSchema>("/metadata/schema/entry-types/field-order", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, field_order: fieldOrder }),
    });
  },
  // Per-type field presentation override (#116): relabel / hide a field for
  // one entry type. `label`/`hidden` are the complete desired overlay — pass
  // null to clear an aspect; both empty drops the override.
  setEntryTypeFieldOverride(
    layerId: string,
    entryTypeId: string,
    fieldKey: string,
    override: { label?: string | null; hidden?: boolean | null },
  ) {
    return request<MetadataSchema>("/metadata/schema/entry-types/field-override", {
      method: "PUT",
      body: JSON.stringify({
        layer_id: layerId,
        entry_type_id: entryTypeId,
        field_key: fieldKey,
        label: override.label ?? null,
        hidden: override.hidden ?? null,
      }),
    });
  },
};
