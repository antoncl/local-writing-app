<script lang="ts">
  // The Detail Types pane's content — everything inside
  // `<section class="pane schema-pane">`: the kind tabs (Scene / Lore /
  // …), the context heading, and the entry-type tree (a NodeList of the
  // recursive renderNodeTypeCard snippet). The pane chrome (header with
  // + Type / Groups… / Tags… / Close, drag, resize) stays in App.svelte
  // because it's part of its pane-layout system.
  //
  // Extracted from App.svelte (#14, third slice). The component owns no
  // long-lived state — the tree is built in the parent's `$:` (so its
  // reactivity tracks metadataSchema refreshes) and threads in as a prop;
  // `draggedSchemaTypeId` binds two-way so the dragover/dragend handlers
  // here and the parent's drop handler share one value. Everything that
  // touches the API or opens the type/field editor comes back as a
  // callback prop.

  import NodeList from "./NodeList.svelte";
  import NodeRow from "./NodeRow.svelte";
  import { resolveColor } from "./colors";
  import { fieldTypeLabel } from "./fieldIcons";
  import { sourceBadgeLabel, type NodeTypeTreeNode, type SchemaKind } from "./schemaTypeHelpers";
  import type { MetadataSchema, MetadataSchemaOverview } from "./types";

  // --- Read-only state ---
  export let schemaFieldKind: SchemaKind = "scene";
  export let schemaContextHeading: string = "";
  export let schemaNodeTypeTree: NodeTypeTreeNode[] = [];
  export let selectedSchemaTypeId: string | null = null;
  export let schemaTypeLayerId: string = "";
  export let metadataSchema: MetadataSchema | null = null;
  export let metadataSchemaOverview: MetadataSchemaOverview | null = null;

  // --- Drag state (two-way bound; shared with the parent's drop handler) ---
  export let draggedSchemaTypeId: string | null = null;

  // --- Callbacks (parent owns the side-effects) ---
  export let projectSchemaLayerId: () => string = () => "";
  export let onSwitchKind: (kind: SchemaKind) => void = () => {};
  export let onCreateType: (layerId: string, parentTypeId: string) => void = () => {};
  export let onOpenType: (typeId: string) => void = () => {};
  export let onStartTypeDrag: (typeId: string) => void = () => {};
  export let onDropTypeOnParent: (parentTypeId: string) => void = () => {};
  export let onCreateField: (layerId: string, entryTypeId: string) => void = () => {};
  export let onDeleteType: (typeId: string) => void = () => {};
  export let onOpenField: (fieldId: string, entryTypeId: string) => void = () => {};

  // The kind tabs, in display order. Mirrors the schema's kind universe.
  const SCHEMA_KINDS: Array<{ id: SchemaKind; label: string }> = [
    { id: "scene", label: "Scene" },
    { id: "lore", label: "Lore" },
    { id: "research", label: "Research" },
    { id: "prompt", label: "Prompt" },
    { id: "assistant", label: "Assistant" },
    { id: "project", label: "Project" },
  ];

  function typeSourceFor(typeId: string) {
    return metadataSchemaOverview?.entry_type_sources[typeId] ?? null;
  }
</script>

<div class="pane-content schema-list">
  <div class="schema-kind-tabs" role="tablist" aria-label="Type kind">
    {#each SCHEMA_KINDS as kind}
      <button
        type="button"
        role="tab"
        aria-selected={schemaFieldKind === kind.id}
        class:active={schemaFieldKind === kind.id}
        on:click={() => onSwitchKind(kind.id)}
      >{kind.label}</button>
    {/each}
  </div>
  <div class="schema-context-heading">
    <strong>{schemaContextHeading}</strong>
    <small>Drag a custom type onto another type to change its parent.</small>
  </div>
  <div class="schema-node-tree" aria-label={`${schemaContextHeading} tree`}>
    <NodeList mode="tree" isEmpty={schemaNodeTypeTree.length === 0}>
      {#snippet whenEmpty()}
        <p class="muted">No detail types defined for this context.</p>
      {/snippet}
      {#each schemaNodeTypeTree as node (node.id)}
        {@render renderNodeTypeCard(node)}
      {/each}
    </NodeList>
  </div>
</div>

{#snippet renderNodeTypeCard(node: NodeTypeTreeNode)}
  {@const typeSource = typeSourceFor(node.id)}
  {@const fieldEntries = node.fieldEntries}
  {@const typeSwatch = resolveColor(null, node.id, node.definition.kind, metadataSchema)}
  {@const stripeHex = typeSwatch?.hex ?? null}
  {@const childCount = fieldEntries.length + node.children.length}
  <NodeRow
    title={node.label}
    detail={`${node.id}${node.definition.abstract ? " · Abstract" : ""}`}
    groupHeader
    stripeColor={stripeHex}
    active={selectedSchemaTypeId === node.id}
    ariaLabel={`${node.label} detail type — ${sourceBadgeLabel(typeSource)}`}
    collapsed={childCount === 0}
    draggable={!typeSource?.built_in}
    onClick={() => onOpenType(node.id)}
    on:dragstart={() => {
      if (!typeSource?.built_in) onStartTypeDrag(node.id);
    }}
    on:dragend={() => (draggedSchemaTypeId = null)}
    on:dragover={(event) => {
      if (draggedSchemaTypeId && draggedSchemaTypeId !== node.id) event.preventDefault();
    }}
    on:drop={(event) => {
      event.preventDefault();
      onDropTypeOnParent(node.id);
    }}
  >
    {#snippet trailing()}
      <span class="group-count-pill" title={`${fieldEntries.length} field${fieldEntries.length === 1 ? "" : "s"}, ${node.children.length} sub-type${node.children.length === 1 ? "" : "s"}`}>{childCount}</span>
      <button class="row-action-add" type="button" title={`Add sub-type to ${node.label}`} aria-label={`Add sub-type to ${node.label}`} on:click={() => onCreateType(schemaTypeLayerId || projectSchemaLayerId(), node.id)}>+ Type</button>
      <button class="row-action-add" type="button" title={`Add field to ${node.label}`} aria-label={`Add field to ${node.label}`} on:click={() => { onOpenType(node.id); onCreateField(schemaTypeLayerId || projectSchemaLayerId(), node.id); }}>+ Field</button>
      {#if !typeSource?.built_in}
        <button class="row-action-delete" type="button" title={`Delete ${node.label}`} aria-label={`Delete ${node.label}`} on:click={() => onDeleteType(node.id)}>×</button>
      {/if}
    {/snippet}
    {#snippet nested()}
      {#each fieldEntries as [fieldId, field] (fieldId)}
        {@const fieldSource = metadataSchemaOverview?.field_sources[fieldId]}
        <NodeRow
          title={field.name}
          ariaLabel={`Field ${fieldId} — ${sourceBadgeLabel(fieldSource)}`}
          onClick={() => { onOpenType(node.id); onOpenField(fieldId, node.id); }}
        >
          {#snippet detailSlot()}
            <small>{fieldId}</small>
          {/snippet}
          {#snippet trailing()}
            <span class="schema-field-type-pill" title={fieldTypeLabel(field.type)}>{field.type}</span>
          {/snippet}
        </NodeRow>
      {/each}
      {#each node.children as child (child.id)}
        {@render renderNodeTypeCard(child)}
      {/each}
    {/snippet}
  </NodeRow>
{/snippet}
