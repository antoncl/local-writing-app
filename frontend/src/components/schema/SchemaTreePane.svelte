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

  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { resolveColor } from "@/lib/utils/colors";
  import { fieldTypeLabel } from "@/lib/utils/fieldIcons";
  import { sourceBadgeLabel, type NodeTypeTreeNode, type SchemaKind } from "@/lib/utils/schemaTypeHelpers";
  import type { MetadataSchemaOverview } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";

  interface Props {
    // --- Read-only state ---
    schemaFieldKind?: SchemaKind;
    schemaContextHeading?: string;
    schemaNodeTypeTree?: NodeTypeTreeNode[];
    selectedSchemaTypeId?: string | null;
    schemaTypeLayerId?: string;
    metadataSchemaOverview?: MetadataSchemaOverview | null;
    // --- Drag state (two-way bound; shared with the parent's drop handler) ---
    draggedSchemaTypeId?: string | null;
    // --- Callbacks (parent owns the side-effects) ---
    projectSchemaLayerId?: () => string;
    onSwitchKind?: (kind: SchemaKind) => void;
    onCreateType?: (layerId: string, parentTypeId: string) => void;
    onOpenType?: (typeId: string) => void;
    onStartTypeDrag?: (typeId: string) => void;
    onDropTypeOnParent?: (parentTypeId: string) => void;
    onCreateField?: (layerId: string, entryTypeId: string) => void;
    onDeleteType?: (typeId: string) => void;
    onOpenField?: (fieldId: string, entryTypeId: string) => void;
  }

  let {
    schemaFieldKind = "scene",
    schemaContextHeading = "",
    schemaNodeTypeTree = [],
    selectedSchemaTypeId = null,
    schemaTypeLayerId = "",
    metadataSchemaOverview = null,
    draggedSchemaTypeId = $bindable(null),
    projectSchemaLayerId = () => "",
    onSwitchKind = () => {},
    onCreateType = () => {},
    onOpenType = () => {},
    onStartTypeDrag = () => {},
    onDropTypeOnParent = () => {},
    onCreateField = () => {},
    onDeleteType = () => {},
    onOpenField = () => {},
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

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
        onclick={() => onSwitchKind(kind.id)}
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
    ondragstart={() => {
      if (!typeSource?.built_in) onStartTypeDrag(node.id);
    }}
    ondragend={() => (draggedSchemaTypeId = null)}
    ondragover={(event) => {
      if (draggedSchemaTypeId && draggedSchemaTypeId !== node.id) event.preventDefault();
    }}
    ondrop={(event) => {
      event.preventDefault();
      onDropTypeOnParent(node.id);
    }}
  >
    {#snippet trailing()}
      <CountPill count={childCount} title={`${fieldEntries.length} field${fieldEntries.length === 1 ? "" : "s"}, ${node.children.length} sub-type${node.children.length === 1 ? "" : "s"}`} />
      <button class="row-action-add" type="button" title={`Add sub-type to ${node.label}`} aria-label={`Add sub-type to ${node.label}`} onclick={() => onCreateType(schemaTypeLayerId || projectSchemaLayerId(), node.id)}>+ Type</button>
      <button class="row-action-add" type="button" title={`Add field to ${node.label}`} aria-label={`Add field to ${node.label}`} onclick={() => { onOpenType(node.id); onCreateField(schemaTypeLayerId || projectSchemaLayerId(), node.id); }}>+ Field</button>
      {#if !typeSource?.built_in}
        <button class="row-action-delete" type="button" title={`Delete ${node.label}`} aria-label={`Delete ${node.label}`} onclick={() => onDeleteType(node.id)}>×</button>
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

<style>
  /* Detail-Types tree pane styles co-located from styles.css (#14). Own
     template DOM (context heading, tree wrapper, kind tabs, and the type
     pill rendered into NodeRow snippets) → scoped, no :global. */
  .schema-context-heading {
    display: grid;
    gap: 2px;
  }

  .schema-context-heading small {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  /* Outer container around the Detail Types NodeList. The NodeList itself
     handles row spacing; this wrapper is here to keep an aria-label hook
     for the recursive tree. */
  .schema-node-tree {
    display: grid;
    gap: 8px;
  }

  /* .schema-source-badge co-located into SchemaTypeEditor.svelte (#14). */

  /* Mono type-pill on field rows in the Detail Types tree — mirrors the
     Editorial Card spec ("Field types sit in mono pills"). Distinguishes
     the field's type vocabulary (`text`, `select`, `entity_ref`…) from the
     neutral count/affordance pills used elsewhere. Tooltip carries the
     humanized label. */
  .schema-field-type-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 7px;
    border-radius: 5px;
    background: var(--inset);
    color: var(--text-3);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: var(--fs-xs);
    font-weight: 600;
    white-space: nowrap;
  }

  /* .migration-applied co-located into Project.svelte (#14). */

  .schema-kind-tabs {
    display: flex;
    gap: 2px;
    margin: 0 -10px 8px;
    padding: 0 10px 6px;
    border-bottom: 1px solid var(--divider);
  }

  .schema-kind-tabs button {
    flex: 1;
    padding: 6px 10px;
    background: transparent;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    border-radius: 4px 4px 0 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
    cursor: pointer;
  }

  .schema-kind-tabs button:hover {
    color: var(--text);
    background: var(--inset);
  }

  .schema-kind-tabs button.active {
    color: var(--accent-deep);
    border-bottom-color: var(--accent-deep);
    font-weight: 600;
  }
</style>
