<script lang="ts">
  // SchemaPanes — the schema-authoring surface, extracted from App.svelte (#14
  // P0). Owns the "Detail Types" tree pane + the per-type editor pane + the
  // reusable-groups manager dialog, plus all the authoring state, the
  // entry-type→kind→tree derivation cascade, and the persistence handlers
  // (create/save/delete type+field, group apply, field reorder). App stays the
  // window-manager host: it passes the shared pane chrome + the error-wrapping
  // `run`, status sink, and editor-pane baseline refresh, and drives the three
  // entry points (open Detail Types, open type for a document's "Edit type…",
  // re-sync authoring selection after a project loads) via `bind:this`.
  import { get } from "svelte/store";
  import { api } from "@/lib/api";
  import Pane, { type PaneChrome } from "@/components/panes/Pane.svelte";
  import SchemaTreePane from "@/components/schema/SchemaTreePane.svelte";
  import SchemaTypeEditor, { type TypeDraftPayload } from "@/components/schema/SchemaTypeEditor.svelte";
  import type { FieldDraftPayload } from "@/components/schema/SchemaFieldInlineEditor.svelte";
  import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";
  import GroupsManagerDialog from "@/components/dialogs/GroupsManagerDialog.svelte";
  import {
    buildNodeTypeTree,
    buildSchemaFieldSections,
    type NodeTypeTreeNode,
    type SchemaKind,
  } from "@/lib/utils/schemaTypeHelpers";
  import {
    metadataSchemaStore,
    metadataSchemaOverviewStore,
    metadataSchemaLayersStore,
    refreshSchema as storeRefreshSchema,
    setMetadataSchema,
    projectSchemaLayerId,
  } from "@/lib/stores/schema";
  import { setValidation } from "@/lib/stores/validation";
  import { paneLayout } from "@/lib/stores/paneLayout.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import type {
    DocumentKind,
    EntryMetadata,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataFieldType,
    MetadataValue,
    PaneId,
    PromptEntryTypeExtras,
    SelectOption,
  } from "@/lib/types";

  interface Props {
    isProjectOpen: boolean;
    // The shared MDI chrome handed to every <Pane> (focus/drag/resize handlers).
    paneChrome: PaneChrome;
    // App's error-wrapping runner — sets App's `error` on throw, returns success.
    run: (action: () => Promise<void>) => Promise<boolean>;
    // App's status-line sink.
    setStatus: (message: string) => void;
    // Re-pull open editor panes after a schema mutation rewrote entry data on
    // disk (field rename / option removal / field delete).
    refreshOpenEditorPaneBaselines: (transform?: (metadata: EntryMetadata) => EntryMetadata) => Promise<void>;
    // The schema pane's "Tags…" button opens App's tag manager (tag management
    // is orthogonal to schema authoring and stays App-owned).
    onOpenTagsManager: () => void;
  }

  let {
    isProjectOpen,
    paneChrome,
    run,
    setStatus,
    refreshOpenEditorPaneBaselines,
    onOpenTagsManager,
  }: Props = $props();

  const focusPane = (id: PaneId) => paneChrome.focus(id);
  const paneStyle = (id: PaneId) => paneLayout.styleFor(id);

  // --- Schema store (read live for reactivity inside the cluster) -------------
  const metadataSchema = $derived($metadataSchemaStore);
  const metadataSchemaOverview = $derived($metadataSchemaOverviewStore);
  const metadataSchemaLayers = $derived($metadataSchemaLayersStore);

  // --- Authoring state --------------------------------------------------------
  let schemaFieldKind = $state<SchemaKind>("scene");
  let schemaFieldLayerId = $state("");
  let schemaFieldEntryType = $state("scene");
  // The field-editing DRAFT (type / name / key / options / default / picker /
  // computed / icon + the inline editor's popover toggles) lives inside
  // SchemaFieldInlineEditor (#14 Step 4). We keep only the context the parent
  // computes from the schema overview: which field is open + whether it's a
  // read-only (built-in) field. The draft arrives back as a payload on save.
  let selectedSchemaFieldId: string | null = $state(null);
  let schemaFieldReadonly = $state(false);
  // L2 reusable-groups manager (modal).
  let groupsManagerOpen = $state(false);
  // Expand-in-place field editing in the type editor: the field id whose inline
  // editor is open (one at a time), or the "__new__" sentinel while adding a
  // field. null = all rows collapsed.
  const NEW_FIELD_SENTINEL = "__new__";
  let expandedSchemaFieldId: string | null = $state(null);
  let schemaPaneOpen = $state(false);
  let schemaTypePaneOpen = $state(false);
  // The save layer is shared with SchemaTreePane, so it stays here; the rest of
  // the type draft (name/id/color + prompt defaults) lives inside
  // SchemaTypeEditor, which we remount per opened/created type via the draft
  // token below and seed from the schemaTypeInit* props (#14 Step 4).
  let schemaTypeLayerId = $state("");
  let schemaTypeKind: SchemaKind = $state("lore");
  let schemaTypeParent = $state("");
  let schemaTypeAbstract = false;
  let schemaTypeReadonly = $state(false);
  let selectedSchemaTypeId: string | null = $state(null);
  let draggedSchemaTypeId: string | null = $state(null);
  let schemaSelectedEntryType: EntryTypeDefinition | null = $state(null);
  let schemaNodeTypeTree: NodeTypeTreeNode[] = $state([]);
  // Seed values for a freshly (re)mounted SchemaTypeEditor draft. The token
  // bumps on every create/open so the keyed component re-initialises cleanly.
  let schemaTypeInitName = $state("");
  let schemaTypeInitId = $state("");
  let schemaTypeInitColor: string | null = $state(null);
  let schemaTypeInitPrompt: PromptEntryTypeExtras | null = $state(null);
  let schemaTypeDraftToken = $state(0);

  // --- Field-row drag-reorder (own fields of a type) --------------------------
  let fieldDragId: string | null = null;
  let fieldDropTarget: { id: string; position: "before" | "after" } | null = $state(null);

  // --- Derived: the entry-type → kind → tree cascade --------------------------
  $effect.pre(() => {
    schemaSelectedEntryType = metadataSchema?.entry_types[schemaFieldEntryType] ?? metadataSchema?.entry_types.scene ?? null;
  });
  $effect.pre(() => {
    schemaFieldKind =
      schemaSelectedEntryType?.kind === "lore"
        ? "lore"
        : schemaSelectedEntryType?.kind === "research"
          ? "research"
          : schemaSelectedEntryType?.kind === "prompt"
            ? "prompt"
            : schemaSelectedEntryType?.kind === "assistant"
              ? "assistant"
              : schemaSelectedEntryType?.kind === "project"
                ? "project"
                : "scene";
  });
  $effect.pre(() => {
    schemaNodeTypeTree = buildNodeTypeTree(metadataSchema, schemaFieldKind);
  });
  // The type-editor field rows. Explicitly reference metadataSchema so these
  // recompute when the schema is refreshed after a save — fieldEntriesFor…
  // reads it *inside* the function, which the template wouldn't track on its
  // own (see feedback-svelte5-reactivity-traps).
  let typeOwnFieldEntries =
    $derived(metadataSchema && selectedSchemaTypeId ? fieldEntriesForEntryType(selectedSchemaTypeId) : []);
  let typeInheritedFieldEntries =
    $derived(metadataSchema && selectedSchemaTypeId ? inheritedFieldEntriesForEntryType(selectedSchemaTypeId) : []);
  let typeOwnFieldSections = $derived(buildSchemaFieldSections(typeOwnFieldEntries));
  let typeInheritedFieldSections = $derived(buildSchemaFieldSections(typeInheritedFieldEntries));
  // L2 reusable groups: the applications on the selected type + the groups
  // available to apply. Reference metadataSchema explicitly so these recompute
  // after a save (see feedback-svelte5-reactivity-traps).
  let typeGroupApplications =
    $derived((metadataSchema && selectedSchemaTypeId
      ? metadataSchema.entry_types[selectedSchemaTypeId]?.group_applications
      : null) ?? []);
  let availableGroupEntries = $derived(Object.entries(metadataSchema?.groups ?? {}));
  let schemaContextHeading =
    $derived(schemaFieldKind === "lore"
      ? "Lore Entry Types"
      : schemaFieldKind === "research"
        ? "Research Types"
        : schemaFieldKind === "prompt"
          ? "Prompt Types"
          : schemaFieldKind === "assistant"
            ? "Assistant Types"
            : schemaFieldKind === "project"
              ? "Project Types"
              : "Scene Types");

  // --- Entry points App still drives (via bind:this) --------------------------
  export function syncSelection() {
    syncSchemaAuthoringSelection();
  }
  export function openForCustomData(entryType: string, kind: DocumentKind) {
    openSchemaForCustomData(entryType, kind);
  }
  export function openDetailTypes() {
    openDetailTypesPane();
  }

  // Re-point the schema-authoring editor's selection at still-valid targets
  // after the schema store changes. Authoring state (not server-mirrored).
  // Reads the store live (`get`) — callers invoke it right after a store set,
  // where the `$store` aliases still lag a flush.
  function syncSchemaAuthoringSelection() {
    const schema = get(metadataSchemaStore);
    if (!schema) return;
    const layers = get(metadataSchemaLayersStore);
    if (!schema.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = schema.entry_types.scene ? "scene" : Object.keys(schema.entry_types)[0] ?? "scene";
    }
    if (!schemaFieldLayerId || !layers.some((layer) => layer.id === schemaFieldLayerId)) {
      schemaFieldLayerId = projectSchemaLayerId();
    }
    if (!schemaTypeLayerId || !layers.some((layer) => layer.id === schemaTypeLayerId)) {
      schemaTypeLayerId = projectSchemaLayerId();
    }
  }

  async function refreshMetadataSchema() {
    await storeRefreshSchema();
    syncSchemaAuthoringSelection();
  }

  function fieldEntriesForEntryType(entryTypeId: string) {
    const entryType = metadataSchema?.entry_types[entryTypeId];
    const fieldIds = entryType?.own_fields ?? entryType?.fields ?? [];
    return fieldIds
      .map((fieldId) => {
        const field = metadataSchema?.fields[fieldId];
        return field ? ([fieldId, field] as [string, MetadataFieldDefinition]) : null;
      })
      .filter((entry): entry is [string, MetadataFieldDefinition] => Boolean(entry));
  }

  function fieldAppliesToEntryType(fieldId: string, entryTypeId: string) {
    return Boolean(metadataSchema?.entry_types[entryTypeId]?.fields.includes(fieldId));
  }

  // Fields this type inherits from its parent/kind — present in `fields` but not
  // in `own_fields`. Rendered dimmed (read-only) in the type editor with a
  // jump-to-parent affordance (metadata revision, mockup B).
  function inheritedFieldEntriesForEntryType(entryTypeId: string) {
    const entryType = metadataSchema?.entry_types[entryTypeId];
    if (!entryType || !Array.isArray(entryType.own_fields)) return [];
    const own = new Set(entryType.own_fields);
    return (entryType.fields ?? [])
      .filter((fieldId) => !own.has(fieldId))
      .map((fieldId) => {
        const field = metadataSchema?.fields[fieldId];
        return field ? ([fieldId, field] as [string, MetadataFieldDefinition]) : null;
      })
      .filter((entry): entry is [string, MetadataFieldDefinition] => Boolean(entry));
  }

  function schemaTypeSource(typeId: string | null) {
    return typeId ? metadataSchemaOverview?.entry_type_sources[typeId] : null;
  }

  // Open the inline editor on an existing field. We set only the editing CONTEXT
  // (which field, its source layer, read-only-ness, target entry type) —
  // SchemaFieldInlineEditor initializes its own draft from the field def it
  // receives as a prop (#14 Step 4).
  function openSchemaFieldDetail(fieldId: string, entryTypeId = schemaFieldEntryType) {
    const field = metadataSchema?.fields[fieldId];
    if (!field) return;
    const targetEntryTypeId = fieldAppliesToEntryType(fieldId, entryTypeId)
      ? entryTypeId
      : (entryTypeIdsForField(fieldId, schemaFieldKind)[0] ?? defaultSchemaEntryType(schemaFieldKind));
    selectedSchemaFieldId = fieldId;
    schemaFieldReadonly = Boolean(metadataSchemaOverview?.field_sources[fieldId]?.built_in);
    schemaFieldLayerId = metadataSchemaOverview?.field_sources[fieldId]?.built_in ? projectSchemaLayerId() : (metadataSchemaOverview?.field_sources[fieldId]?.layer_id ?? projectSchemaLayerId());
    schemaFieldEntryType = targetEntryTypeId;
    expandedSchemaFieldId = fieldId;
  }

  function createSchemaFieldDraft(layerId = projectSchemaLayerId(), entryTypeId = schemaFieldEntryType) {
    selectedSchemaFieldId = null;
    schemaFieldReadonly = false;
    schemaFieldLayerId = layerId;
    schemaFieldEntryType = entryTypeId;
    expandedSchemaFieldId = NEW_FIELD_SENTINEL;
  }

  // Toggle a field row's inline editor (one open at a time).
  function toggleSchemaFieldInline(fieldId: string, entryTypeId: string) {
    if (expandedSchemaFieldId === fieldId) {
      expandedSchemaFieldId = null;
      return;
    }
    openSchemaFieldDetail(fieldId, entryTypeId);
  }

  function createSchemaTypeDraft(layerId = projectSchemaLayerId(), parentTypeId = "") {
    selectedSchemaTypeId = null;
    const parentType = parentTypeId ? metadataSchema?.entry_types[parentTypeId] : null;
    schemaTypeKind =
      parentType?.kind === "scene"
        ? "scene"
        : parentType?.kind === "lore"
          ? "lore"
          : parentType?.kind === "prompt"
            ? "prompt"
            : parentType?.kind === "assistant"
              ? "assistant"
              : schemaFieldKind;
    schemaTypeParent = parentTypeId || (schemaSelectedEntryType?.abstract || schemaFieldEntryType !== "scene" ? schemaFieldEntryType : defaultSchemaParentType(schemaFieldKind));
    schemaTypeAbstract = false;
    schemaTypeReadonly = false;
    schemaTypeLayerId = layerId;
    schemaTypeInitName = "";
    schemaTypeInitId = "";
    schemaTypeInitColor = null;
    schemaTypeInitPrompt = null;
    schemaTypeDraftToken += 1;
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function openSchemaTypeDetail(typeId: string) {
    const entryType = metadataSchema?.entry_types[typeId];
    if (!entryType) return;
    const source = schemaTypeSource(typeId);
    selectedSchemaTypeId = typeId;
    schemaTypeKind =
      entryType.kind === "scene"
        ? "scene"
        : entryType.kind === "prompt"
          ? "prompt"
          : entryType.kind === "assistant"
            ? "assistant"
            : "lore";
    schemaTypeParent = entryType.parent ?? "";
    schemaTypeAbstract = Boolean(entryType.abstract);
    schemaTypeReadonly = Boolean(source?.built_in);
    schemaTypeLayerId = source?.built_in ? projectSchemaLayerId() : (source?.layer_id ?? projectSchemaLayerId());
    schemaTypeInitName = entryType.name;
    schemaTypeInitId = typeId;
    // Seed own-color (pre-inheritance). null = "inherit from parent", which the
    // SwatchPicker renders as the "None" cell.
    schemaTypeInitColor = entryType.own_color ?? null;
    schemaTypeInitPrompt = entryType.prompt ?? null;
    schemaTypeDraftToken += 1;
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function defaultSchemaParentType(kind: SchemaKind) {
    if (kind === "lore" && metadataSchema?.entry_types.lore_entry) return "lore_entry";
    if (kind === "prompt" && metadataSchema?.entry_types.prompt) return "prompt";
    if (kind === "research" && metadataSchema?.entry_types.research) return "research";
    return "";
  }

  function openSchemaForCustomData(entryType: string, kind: DocumentKind) {
    // Phase B: the entry editor's "Edit type…" button opens ONLY the per-type
    // editor (schema_type pane) — not the schema/tree hierarchy view. Tree
    // access is the top bar's "Detail Types" button.
    // The dispatched DocumentKind is wider than the schema's kind universe (it
    // includes chat / snippet / structure_node — none of which have their own
    // schema-type tree); narrow before consulting the schema.
    if (kind !== "scene" && kind !== "lore" && kind !== "research" && kind !== "prompt" && kind !== "assistant" && kind !== "project") return;
    const candidate = metadataSchema?.entry_types[entryType];
    const resolvedTypeId = candidate?.kind === kind ? entryType : defaultSchemaEntryType(kind);
    schemaFieldEntryType = resolvedTypeId;
    if (resolvedTypeId && metadataSchema?.entry_types[resolvedTypeId]) {
      openSchemaTypeDetail(resolvedTypeId);
    } else {
      // No matching type — fall back to opening the tree so the user can pick or
      // create one. Rare edge case for new projects.
      schemaPaneOpen = true;
      focusPane("schema");
    }
  }

  // Top-bar entry point: opens the schema/tree pane (the canonical hierarchy
  // editor). The per-type editor opened from individual entries goes via
  // openSchemaTypeDetail instead — see Phase B's split.
  function openDetailTypesPane() {
    if (!isProjectOpen) return;
    schemaPaneOpen = true;
    focusPane("schema");
  }

  // Switches the tree's scope. schemaFieldKind is derived from
  // schemaFieldEntryType via the cascade above — to switch kinds we set
  // entryType to a default of the target kind. The cascade updates
  // schemaContextHeading and schemaNodeTypeTree on the next tick.
  function switchSchemaKind(kind: SchemaKind) {
    schemaFieldEntryType = defaultSchemaEntryType(kind);
  }

  function defaultSchemaEntryType(kind: SchemaKind) {
    const fallback = kind === "lore" ? "lore_note" : kind === "research" ? "note" : kind === "prompt" ? "prompt" : kind === "assistant" ? "assistant" : kind === "project" ? "project" : "scene";
    return Object.entries(metadataSchema?.entry_types ?? {}).find(([, definition]) => definition.kind === kind)?.[0] ?? fallback;
  }

  function entryTypeIdsForField(fieldId: string, kind: SchemaKind) {
    return Object.entries(metadataSchema?.entry_types ?? {})
      .filter(([, definition]) => definition.kind === kind && definition.fields.includes(fieldId))
      .map(([typeId]) => typeId);
  }

  function closeSchemaPane(id: "schema" | "schema_type") {
    if (id === "schema") schemaPaneOpen = false;
    else schemaTypePaneOpen = false;
  }

  function startSchemaTypeDrag(typeId: string) {
    draggedSchemaTypeId = typeId;
  }

  async function dropSchemaTypeOnParent(parentTypeId: string) {
    const typeId = draggedSchemaTypeId;
    draggedSchemaTypeId = null;
    if (!typeId || typeId === parentTypeId) return;
    const entryType = metadataSchema?.entry_types[typeId];
    const parentType = metadataSchema?.entry_types[parentTypeId];
    if (!entryType || !parentType || entryType.kind !== parentType.kind) return;
    const source = schemaTypeSource(typeId);
    if (!source || source.built_in) {
      setStatus("System detail types cannot be moved");
      return;
    }
    await run(async () => {
      setMetadataSchema(await api.upsertMetadataEntryType(
        source.layer_id,
        typeId,
        {
          ...entryType,
          parent: parentTypeId,
        },
        true,
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      selectedSchemaTypeId = typeId;
      setStatus(`Moved ${entryType.name} under ${parentType.name}`);
    });
  }

  // Coerce the editor-side string default onto the field-type's wire shape
  // (#38). Mirrors NodeEditor.defaultValueForStorage for prompt inputs; returns
  // undefined for empty (no default) and computed types.
  function schemaFieldDefaultForStorage(
    type: MetadataFieldType,
    raw: string | undefined,
  ): MetadataValue | undefined {
    if (raw === undefined || raw === "") return undefined;
    if (type === "boolean") return raw === "true";
    if (type === "number") {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    return raw;
  }

  // The draft arrives assembled from SchemaFieldInlineEditor (#14 Step 4); we
  // own the persistence (option migration, removed-value confirm, rename,
  // refresh) plus the editing context (layer / entry-type / previous id).
  async function saveSchemaField(payload: FieldDraftPayload) {
    if (!schemaFieldLayerId) return;
    const layerId = schemaFieldLayerId;
    const entryType = schemaFieldEntryType;
    const previousFieldId = selectedSchemaFieldId && !selectedSchemaFieldId.startsWith("system:") ? selectedSchemaFieldId : null;
    const nextFieldId = payload.id.trim();
    // Compose SelectOption objects from the ordered draft list (order is
    // preserved on save). Drop rows with an empty value; de-dupe by value.
    const seenValues = new Set<string>();
    const options = payload.options
      .map((draft) => ({ ...draft, value: draft.value.trim() }))
      .filter((draft) => draft.value && !seenValues.has(draft.value) && seenValues.add(draft.value))
      .map((draft) => {
        const out: SelectOption = { value: draft.value };
        const label = draft.label.trim();
        // Only persist a label when it differs from the stable value (label is
        // cosmetic; value is the macro contract).
        if (label && label !== draft.value) out.label = label;
        if (draft.color) out.color = draft.color;
        return out;
      });
    // Migration: a row whose value changed from its loaded `originalValue`
    // rewrites stored entry data. Reorder-safe (keyed by originalValue, not
    // position); added rows have no originalValue so they never migrate.
    const optionMigration = buildOptionMigrationFromDrafts(payload.options);
    const hasOptions = payload.type === "select" || payload.type === "multi_select";
    const hasPicker = payload.type === "entity_ref" || payload.type === "entity_ref_list";
    const computedSpec: Record<string, string> | null =
      payload.type === "computed"
        ? payload.computedFunction === "word_count"
          ? { source: "body", function: "word_count" }
          : { function: "counter", scope: payload.computedScope }
        : null;
    // Coerce the editor-side string default into the field-type's wire shape
    // (#38). Computed fields never carry a default. undefined / "" → omit the
    // key entirely so the field stays defaultless rather than seeding a falsy
    // value into new entries.
    const defaultValue =
      payload.type === "computed" ? undefined : schemaFieldDefaultForStorage(payload.type, payload.defaultValue);
    const nextField: MetadataFieldDefinition = {
      name: payload.name.trim() || nextFieldId,
      type: payload.type,
      options: hasOptions ? options : [],
      ...(hasPicker ? { picker_config: payload.pickerConfig } : {}),
      ...(computedSpec ? { computed: computedSpec } : {}),
      ...(payload.group.trim() ? { group: payload.group.trim() } : {}),
      // Per-field icon override (chosen in the IconPicker). null/empty = fall
      // back to the field-type default glyph.
      ...(payload.icon ? { icon: payload.icon } : {}),
      ...(defaultValue !== undefined ? { default: defaultValue } : {}),
    };

    // Detect option values that are being removed (present before, gone now, and
    // not a rename source) — those get cleared from existing documents.
    const previousField = previousFieldId ? metadataSchema?.fields[previousFieldId] : null;
    const newValueSet = new Set(options.map((o) => o.value));
    const renameKeys = new Set(Object.keys(optionMigration ?? {}));
    const removedValues = hasOptions && previousField && (previousField.type === "select" || previousField.type === "multi_select")
      ? previousField.options.map((o) => o.value).filter((v) => !newValueSet.has(v) && !renameKeys.has(v))
      : [];

    const persist = () => persistSchemaField({ layerId, entryType, previousFieldId, nextFieldId, nextField, optionMigration });

    if (removedValues.length > 0) {
      confirmService.request({
        title: removedValues.length > 1 ? "Remove these option values?" : "Remove this option value?",
        message: `Removing ${removedValues.join(", ")} will clear ${removedValues.length > 1 ? "them" : "it"} from every document that currently uses ${removedValues.length > 1 ? "them" : "it"}.`,
        confirmLabel: "Remove & save",
        destructive: true,
        cannotBeUndone: true,
        dontShowAgainKey: "removeSelectOptions",
        onConfirm: persist,
      });
    } else {
      await run(persist);
    }
  }

  async function persistSchemaField(args: {
    layerId: string;
    entryType: string;
    previousFieldId: string | null;
    nextFieldId: string;
    nextField: MetadataFieldDefinition;
    optionMigration: Record<string, string> | null;
  }) {
    const { layerId, entryType, previousFieldId, nextFieldId, nextField, optionMigration } = args;
    if (previousFieldId && previousFieldId !== nextFieldId) {
      await api.renameMetadataField(previousFieldId, nextFieldId, entryType);
    }
    setMetadataSchema(await api.upsertMetadataField(layerId, nextFieldId, nextField, entryType, Boolean(previousFieldId), optionMigration));
    await refreshMetadataSchema();
    if (previousFieldId) {
      // The backend rewrote entry data on disk (key rename + option
      // rename/removal); re-pull open panes so they reflect the cleaned data.
      await refreshOpenEditorPaneBaselines();
    }
    setValidation(await api.validateProject());
    selectedSchemaFieldId = nextFieldId;
    // Collapse the inline editor on a successful save.
    expandedSchemaFieldId = null;
    setStatus("Updated details schema");
  }

  // The apply-group form lives in SchemaTypeEditor; it builds the application
  // and awaits this handler, resetting its own form only on a true result.
  async function applyGroupToType(
    application: { group_id: string; label: string; key_prefix: string },
  ): Promise<boolean> {
    if (!selectedSchemaTypeId || !application.group_id) return false;
    const typeId = selectedSchemaTypeId;
    return run(async () => {
      setMetadataSchema(await api.setEntryTypeGroupApplications(
        schemaTypeLayerId || projectSchemaLayerId(),
        typeId,
        [...typeGroupApplications, application],
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      setStatus("Applied group");
    });
  }

  async function removeGroupApplication(index: number) {
    if (!selectedSchemaTypeId) return;
    const typeId = selectedSchemaTypeId;
    const next = typeGroupApplications.filter((_, i) => i !== index);
    await run(async () => {
      setMetadataSchema(await api.setEntryTypeGroupApplications(
        schemaTypeLayerId || projectSchemaLayerId(),
        typeId,
        next,
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      setStatus("Removed group application");
    });
  }

  // SchemaTypeEditor owns the editable draft (name/id/color + prompt defaults)
  // and emits it here; we combine it with the read-only context we still hold
  // (kind/parent/abstract/readonly/selected) + the bound save layer.
  async function saveSchemaType(payload: TypeDraftPayload) {
    if (!schemaTypeLayerId) return;
    await run(async () => {
      const previousTypeId = selectedSchemaTypeId && !schemaTypeReadonly ? selectedSchemaTypeId : null;
      const nextTypeId = payload.typeId.trim();
      const existing = previousTypeId ? metadataSchema?.entry_types[previousTypeId] : null;
      const nextType: EntryTypeDefinition = {
        name: payload.name.trim() || nextTypeId,
        kind: schemaTypeKind,
        parent: schemaTypeParent || null,
        abstract: schemaTypeAbstract,
        fields: previousTypeId ? (existing?.own_fields ?? existing?.fields ?? []) : [],
        color: payload.color || null,
        ...(schemaTypeKind === "prompt" ? { prompt: payload.promptExtras } : {}),
      };
      if (previousTypeId && previousTypeId !== nextTypeId) {
        setStatus("Renaming detail types is not available yet");
        return;
      }
      setMetadataSchema(await api.upsertMetadataEntryType(schemaTypeLayerId, nextTypeId, nextType, Boolean(previousTypeId)));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      selectedSchemaTypeId = nextTypeId;
      schemaFieldEntryType = nextTypeId;
      setStatus("Updated detail type");
    });
  }

  function requestDeleteSchemaType(typeId: string) {
    const definition = metadataSchema?.entry_types[typeId];
    if (!definition) return;
    const source = schemaTypeSource(typeId);
    if (source?.built_in) return;
    const typeName = definition.name || typeId;
    confirmService.request({
      title: "Delete Detail Type",
      message: `Delete "${typeName}"? Existing documents using this type must be changed first.`,
      confirmLabel: "Delete Type",
      destructive: true,
      cannotBeUndone: true,
      dontShowAgainKey: "deleteType",
      onConfirm: () => deleteSchemaType(typeId),
    });
  }

  async function deleteSchemaType(typeId: string) {
    const deletedKind = schemaFieldKind;
    setMetadataSchema(await api.deleteMetadataEntryType(typeId));
    await refreshMetadataSchema();
    setValidation(await api.validateProject());
    selectedSchemaTypeId = null;
    schemaTypePaneOpen = false;
    if (schemaFieldEntryType === typeId || !metadataSchema?.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = defaultSchemaEntryType(deletedKind);
    }
    setStatus(`Deleted ${typeId}`);
  }

  function requestDeleteSchemaField() {
    if (!selectedSchemaFieldId || selectedSchemaFieldId.startsWith("system:") || schemaFieldReadonly) return;
    const fieldName = metadataSchema?.fields[selectedSchemaFieldId]?.name || selectedSchemaFieldId;
    confirmService.request({
      title: "Delete Detail Field",
      message: `Delete "${fieldName}"? This removes the field definition and removes that metadata value from every document using it.`,
      confirmLabel: "Delete Field",
      destructive: true,
      cannotBeUndone: true,
      dontShowAgainKey: "deleteField",
      onConfirm: () => deleteSchemaField(selectedSchemaFieldId!),
    });
  }

  async function deleteSchemaField(fieldId: string) {
    setMetadataSchema(await api.deleteMetadataField(fieldId, schemaFieldEntryType));
    await refreshMetadataSchema();
    await refreshOpenEditorPaneBaselines((metadata) => removeMetadataKey(metadata, fieldId));
    setValidation(await api.validateProject());
    selectedSchemaFieldId = null;
    expandedSchemaFieldId = null;
    setStatus(`Deleted ${fieldId}`);
  }

  function removeMetadataKey(metadata: EntryMetadata, fieldId: string) {
    if (!(fieldId in metadata)) return metadata;
    const nextMetadata = JSON.parse(JSON.stringify(metadata ?? {})) as EntryMetadata;
    delete nextMetadata[fieldId];
    return nextMetadata;
  }

  // Migration from the option draft list: a row whose value changed from the
  // value it was loaded with rewrites stored entry data. Keyed by the loaded
  // `originalValue`, so reordering rows never produces a spurious migration, and
  // freshly-added rows (originalValue null) never migrate.
  function buildOptionMigrationFromDrafts(drafts: OptionDraft[]): Record<string, string> | null {
    const migration: Record<string, string> = {};
    for (const draft of drafts) {
      const value = draft.value.trim();
      if (draft.originalValue && value && draft.originalValue !== value) {
        migration[draft.originalValue] = value;
      }
    }
    return Object.keys(migration).length > 0 ? migration : null;
  }

  // Shared drop-position helper: before/after based on cursor vs row midpoint.
  // Mirrors the NodeRow tree-drag marker so every reorderable list reads the
  // same way (a 2px accent insertion line; see .drop-before/.drop-after CSS).
  function dropPositionFromEvent(event: DragEvent): "before" | "after" {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    return event.clientY < rect.top + rect.height / 2 ? "before" : "after";
  }
  // Reorder helper: move `from` index to before/after `to` index.
  function reorderByPosition<T>(list: T[], from: number, to: number, position: "before" | "after"): T[] {
    if (from < 0 || to < 0) return list;
    const next = [...list];
    const [moved] = next.splice(from, 1);
    let insertAt = to > from ? to - 1 : to;
    if (position === "after") insertAt += 1;
    next.splice(insertAt, 0, moved);
    return next;
  }

  function onFieldDragStart(fieldId: string) {
    fieldDragId = fieldId;
  }
  function onFieldDragOver(event: DragEvent, fieldId: string) {
    if (!fieldDragId || fieldId === fieldDragId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    fieldDropTarget = { id: fieldId, position: dropPositionFromEvent(event) };
  }
  function clearFieldDrag() {
    fieldDragId = null;
    fieldDropTarget = null;
  }
  async function onFieldDrop(targetFieldId: string) {
    const draggedId = fieldDragId;
    const position = fieldDropTarget?.position ?? "before";
    clearFieldDrag();
    if (!draggedId || draggedId === targetFieldId || !selectedSchemaTypeId) return;
    const current = typeOwnFieldEntries.map(([id]) => id);
    const order = reorderByPosition(current, current.indexOf(draggedId), current.indexOf(targetFieldId), position);
    if (order.join(" ") === current.join(" ")) return;
    const layerId = schemaTypeLayerId || projectSchemaLayerId();
    await run(async () => {
      // Reorder is layer-invariant: the backend guard requires an existing
      // override at this layer, so it can't change the overview's
      // field_sources / entry_type_sources / layers. Write through the new
      // effective schema and re-validate the authoring selection locally — no
      // overview refetch needed (the only schema site where that holds).
      setMetadataSchema(await api.setEntryTypeFieldOrder(layerId, selectedSchemaTypeId!, order));
      syncSchemaAuthoringSelection();
      setStatus("Reordered fields");
    });
  }
</script>

<Pane id="schema" title="Detail Types" paneClass="schema-pane" hidden={!isProjectOpen || !schemaPaneOpen} style={paneStyle("schema")} chrome={paneChrome}>
  {#snippet actions()}
    <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => createSchemaTypeDraft()}>+ Type</button>
    <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => (groupsManagerOpen = true)}>Groups…</button>
    <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => onOpenTagsManager()}>Tags…</button>
    <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => closeSchemaPane("schema")}>Close</button>
  {/snippet}
  <SchemaTreePane
    bind:draggedSchemaTypeId
    schemaFieldKind={schemaFieldKind}
    schemaContextHeading={schemaContextHeading}
    schemaNodeTypeTree={schemaNodeTypeTree}
    selectedSchemaTypeId={selectedSchemaTypeId}
    schemaTypeLayerId={schemaTypeLayerId}
    metadataSchemaOverview={metadataSchemaOverview}
    projectSchemaLayerId={projectSchemaLayerId}
    onSwitchKind={switchSchemaKind}
    onCreateType={createSchemaTypeDraft}
    onOpenType={openSchemaTypeDetail}
    onStartTypeDrag={startSchemaTypeDrag}
    onDropTypeOnParent={dropSchemaTypeOnParent}
    onCreateField={createSchemaFieldDraft}
    onDeleteType={requestDeleteSchemaType}
    onOpenField={openSchemaFieldDetail}
  />
</Pane>

<Pane id="schema_type" title="Detail Type" paneClass="schema-type-pane" hidden={!isProjectOpen || !schemaTypePaneOpen} style={paneStyle("schema_type")} chrome={paneChrome}>
  {#snippet actions()}
    <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => closeSchemaPane("schema_type")}>Close</button>
  {/snippet}
  {#key schemaTypeDraftToken}
  <SchemaTypeEditor
    initialName={schemaTypeInitName}
    initialTypeId={schemaTypeInitId}
    initialColor={schemaTypeInitColor}
    initialPrompt={schemaTypeInitPrompt}
    bind:schemaTypeLayerId
    bind:expandedSchemaFieldId
    bind:fieldDropTarget
    schemaTypeKind={schemaTypeKind}
    schemaTypeParent={schemaTypeParent}
    schemaTypeReadonly={schemaTypeReadonly}
    selectedSchemaTypeId={selectedSchemaTypeId}
    selectedSchemaFieldId={selectedSchemaFieldId}
    schemaFieldReadonly={schemaFieldReadonly}
    schemaFieldLayerId={schemaFieldLayerId}
    metadataSchemaOverview={metadataSchemaOverview}
    metadataSchemaLayers={metadataSchemaLayers}
    typeOwnFieldEntries={typeOwnFieldEntries}
    typeInheritedFieldEntries={typeInheritedFieldEntries}
    typeOwnFieldSections={typeOwnFieldSections}
    typeInheritedFieldSections={typeInheritedFieldSections}
    typeGroupApplications={typeGroupApplications}
    availableGroupEntries={availableGroupEntries}
    NEW_FIELD_SENTINEL={NEW_FIELD_SENTINEL}
    projectSchemaLayerId={projectSchemaLayerId}
    onSaveType={saveSchemaType}
    onSaveField={saveSchemaField}
    onCancelField={() => (expandedSchemaFieldId = null)}
    onRemoveField={requestDeleteSchemaField}
    onToggleFieldInline={toggleSchemaFieldInline}
    onCreateFieldDraft={createSchemaFieldDraft}
    onApplyGroup={applyGroupToType}
    onRemoveGroupApplication={removeGroupApplication}
    onFieldDragStart={onFieldDragStart}
    onFieldDragOver={onFieldDragOver}
    onFieldDrop={onFieldDrop}
    onClearFieldDrag={clearFieldDrag}
  />
  {/key}
</Pane>

{#if groupsManagerOpen && metadataSchema}
  <GroupsManagerDialog
    groups={metadataSchema.groups ?? {}}
    layerId={schemaTypeLayerId || projectSchemaLayerId()}
    onChanged={(detail) => { setMetadataSchema(detail.schema); void refreshMetadataSchema(); }}
    onClose={() => (groupsManagerOpen = false)}
  />
{/if}
