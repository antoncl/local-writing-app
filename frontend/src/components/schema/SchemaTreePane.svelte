<script lang="ts">
  // The Types pane's content — everything inside
  // `<section class="pane schema-pane">`: the kind tabs (Scene / Lore /
  // …), the context heading, and the entry-type tree (a NodeList of the
  // recursive renderNodeTypeCard snippet). The pane chrome (header with
  // + Type / Tags… / Close, drag, resize) stays in App.svelte
  // because it's part of its pane-layout system. (Groups is now managed
  // from the per-type editor's Reusable-groups section, not a header
  // button — #607.)
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
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import SchemaTypeCreateForm from "@/components/schema/SchemaTypeCreateForm.svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { resolveColor } from "@/lib/utils/colors";
  import { entryTypeIconClass, fieldTypeLabel } from "@/lib/utils/fieldIcons";
  import {
    sourceBadgeLabel,
    SCHEMA_KINDS as SCHEMA_KIND_ORDER,
    SCHEMA_KIND_META,
    type NodeTypeTreeNode,
    type SchemaKind,
  } from "@/lib/utils/schemaTypeHelpers";
  import type { MetadataSchemaLayer, MetadataSchemaOverview } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";

  interface Props {
    // --- Read-only state ---
    schemaFieldKind?: SchemaKind;
    schemaContextHeading?: string;
    schemaNodeTypeTree?: NodeTypeTreeNode[];
    selectedSchemaTypeId?: string | null;
    schemaTypeLayerId?: string;
    metadataSchemaOverview?: MetadataSchemaOverview | null;
    // --- Inline create form (#1659) ---
    // undefined = closed; a type FQN = the create card is open nested under that
    // type, seeding `extends` with it. The kind root (for the header "+") vs a
    // clicked row (for a row "+") is just what it's seeded with.
    createSeedParentId?: string | undefined;
    kindRootId?: string;
    metadataSchemaLayers?: MetadataSchemaLayer[];
    // --- Drag state (two-way bound; shared with the parent's drop handler) ---
    draggedSchemaTypeId?: string | null;
    // --- Callbacks (parent owns the side-effects) ---
    projectSchemaLayerId?: () => string;
    onSwitchKind?: (kind: SchemaKind) => void;
    // Open the inline create card under `parentTypeId` (a row "+"; the header "+"
    // is opened by the parent at the kind root).
    onRequestCreate?: (parentTypeId: string) => void;
    onSubmitCreate?: (payload: { name: string; parentId: string; layerId: string; localKey: string }) => void;
    onCancelCreate?: () => void;
    onOpenType?: (typeId: string) => void;
    onStartTypeDrag?: (typeId: string) => void;
    onDropTypeOnParent?: (parentTypeId: string) => void;
    onDeleteType?: (typeId: string) => void;
    onOpenField?: (fieldId: string, entryTypeId: string) => void;
  }

  let {
    schemaFieldKind = "manuscript",
    schemaContextHeading = "",
    schemaNodeTypeTree = [],
    selectedSchemaTypeId = null,
    schemaTypeLayerId = "",
    metadataSchemaOverview = null,
    createSeedParentId = undefined,
    kindRootId = "",
    metadataSchemaLayers = [],
    draggedSchemaTypeId = $bindable(null),
    projectSchemaLayerId = () => "",
    onSwitchKind = () => {},
    onRequestCreate = () => {},
    onSubmitCreate = () => {},
    onCancelCreate = () => {},
    onOpenType = () => {},
    onStartTypeDrag = () => {},
    onDropTypeOnParent = () => {},
    onDeleteType = () => {},
    onOpenField = () => {},
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  // The kind tabs, in display order — labels from the shared kind table so the
  // strip and the SchemaPanes cascade can never disagree on the kind set (#729).
  const SCHEMA_KINDS: Array<{ id: SchemaKind; label: string }> = SCHEMA_KIND_ORDER.map((id) => ({
    id,
    label: SCHEMA_KIND_META[id].label,
  }));

  function typeSourceFor(typeId: string) {
    return metadataSchemaOverview?.entry_type_sources[typeId] ?? null;
  }

  // Ephemeral collapse state for the type tree (ADR-0066 Amendment 1, S5): the
  // pane previously had no way to collapse a type's fields/sub-types. View-only
  // state, so it lives here (the tree data still comes from the parent).
  const collapsedTypes = new SvelteSet<string>();
  function toggleType(typeId: string): void {
    if (collapsedTypes.has(typeId)) collapsedTypes.delete(typeId);
    else collapsedTypes.add(typeId);
  }
</script>

<div class="pane-content schema-list">
  <div class="tab-strip schema-kind-tabs" role="tablist" aria-label="Type kind">
    {#each SCHEMA_KINDS as kind}
      <button
        type="button"
        class="tab-strip-tab"
        role="tab"
        aria-selected={schemaFieldKind === kind.id}
        class:active={schemaFieldKind === kind.id}
        onclick={() => onSwitchKind(kind.id)}
      >{kind.label}</button>
    {/each}
  </div>
  <div class="schema-context-heading">
    <div class="sch-heading-row">
      <strong>{schemaContextHeading}</strong>
      <!-- The one always-visible "start a new type" entry (#1662): opens the
           inline create card seeded at the kind root (a top-level type; extends
           still editable). A row's "+" seeds a child instead. -->
      <button class="sch-new-type" type="button" onclick={() => onRequestCreate(kindRootId)}>
        <span aria-hidden="true">+</span> New type
      </button>
    </div>
    <small>Drag a custom type onto another type to change its parent.</small>
  </div>
  <div class="schema-node-tree" aria-label={`${schemaContextHeading} tree`}>
    <NodeList mode="tree" isEmpty={schemaNodeTypeTree.length === 0}>
      {#snippet whenEmpty()}
        <p class="muted">No types defined for this context.</p>
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
  {@const typeGlyph = entryTypeIconClass(node.id, metadataSchema)}
  {@const childCount = fieldEntries.length + node.children.length}
  {@const isCollapsed = collapsedTypes.has(node.id)}
  <NodeRow
    title={node.label}
    detail={`${node.id}${node.definition.abstract ? " · Abstract" : ""}`}
    groupHeader
    stripeColor={stripeHex}
    typeIcon={typeGlyph}
    active={selectedSchemaTypeId === node.id}
    ariaLabel={`${node.label} type — ${sourceBadgeLabel(typeSource)}`}
    collapsed={createSeedParentId === node.id ? false : childCount === 0 || isCollapsed}
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
    {#snippet leading()}
      <!-- Interactive collapse for a type with fields/sub-types; a childless
           type reserves the same gutter (empty) so titles align (S5). -->
      <RowCaret
        collapsible={childCount > 0}
        collapsed={isCollapsed}
        toggle={() => toggleType(node.id)}
        size="md"
      />
    {/snippet}
    {#snippet trailing()}
      <CountPill count={childCount} title={`${fieldEntries.length} field${fieldEntries.length === 1 ? "" : "s"}, ${node.children.length} sub-type${node.children.length === 1 ? "" : "s"}`} />
      <button class="row-action-add" type="button" title={`Add sub-type to ${node.label}`} aria-label={`Add sub-type to ${node.label}`} onclick={() => onRequestCreate(node.id)}>+</button>
      {#if !typeSource?.built_in}
        <button class="row-action-delete" type="button" title={`Delete ${node.label}`} aria-label={`Delete ${node.label}`} onclick={() => onDeleteType(node.id)}>×</button>
      {/if}
    {/snippet}
    {#snippet nested()}
      {#if createSeedParentId === node.id}
        <!-- Rendered FIRST so the create card sits immediately under the row whose
             "+" opened it — not buried beneath the parent's fields and sub-types
             (#1659). -->
        <SchemaTypeCreateForm
          kind={schemaFieldKind}
          seedParentId={node.id}
          kindRootId={kindRootId}
          layers={metadataSchemaLayers}
          defaultLayerId={schemaTypeLayerId || projectSchemaLayerId()}
          onSubmit={onSubmitCreate}
          onCancel={onCancelCreate}
        />
      {/if}
      {#each fieldEntries as [fieldId, field] (fieldId)}
        {@const fieldSource = metadataSchemaOverview?.field_sources[fieldId]}
        <NodeRow
          title={field.name}
          ariaLabel={`Field ${fieldId} — ${sourceBadgeLabel(fieldSource)}`}
          onClick={() => { onOpenType(node.id); onOpenField(fieldId, node.id); }}
        >
          {#snippet leading()}
            <!-- Reserve the caret gutter so a field's title aligns with a
                 sibling sub-type's caret'd title (S5). -->
            <RowCaret collapsible={false} size="md" />
          {/snippet}
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

  /* Heading row: the "<Kind> Types" title on the left, the always-visible
     "+ New type" affordance pinned right (#1662). */
  .sch-heading-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .sch-new-type {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 9px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
    cursor: pointer;
  }

  .sch-new-type:hover {
    background: var(--panel);
    border-color: var(--accent-emphasis);
    color: var(--accent-emphasis);
  }

  .schema-context-heading small {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  /* Outer container around the Types NodeList. The NodeList itself
     handles row spacing; this wrapper is here to keep an aria-label hook
     for the recursive tree. */
  .schema-node-tree {
    display: grid;
    gap: 8px;
  }

  /* .schema-source-badge co-located into SchemaTypeEditor.svelte (#14). */

  /* Mono type-pill on field rows in the Types tree — mirrors the
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
    font-family: var(--mono);
    font-size: var(--fs-xs);
    font-weight: 600;
    white-space: nowrap;
  }

  /* .migration-applied co-located into Project.svelte (#14). */

  /* Uses the shared .tab-strip / .tab primitives (#610). Kept here: the
     negative-margin bleed to the pane edges, the extra bottom padding, and
     equal-width tabs (flex:1) — these tabs fill the row rather than sitting at
     their natural width like the Settings tabs. */
  .schema-kind-tabs {
    margin: 0 -10px 8px;
    padding: 0 10px 6px;
  }

  .schema-kind-tabs button.tab-strip-tab {
    flex: 1;
  }
</style>
