<script context="module" lang="ts">
  import type { StructureDocument, StructureNode, StructureNodeDeletePreview } from "@/lib/types";

  // Per-kind tree config. The manuscript and research panes both render
  // hierarchical NodeRow trees with the same leaf/container shape; the only
  // differences (drag, status stripe, leaf-open API, cascade-preview labels,
  // etc.) live here so one component serves both. Add a third tree by passing
  // another TreeConfig. App owns the structure data + editor-pane coupling
  // (delete, collapse, dblclick-open); this component owns the rendering and
  // the inline CRUD (add / rename / drag-reorder).
  export type TreeConfig = {
    kind: "scene" | "research";
    leafType: string;
    // Live read of App's structure. Used inside handlers (after a mutation the
    // `structure` *prop* is stale until the next tick, but this closure is
    // always current).
    getStructure: () => StructureDocument | null;
    applyStructure: (next: StructureDocument) => void;
    refresh: () => Promise<void>;
    api: {
      create: (title: string, entryType: string, parentId: string | null) => Promise<StructureDocument>;
      rename: (nodeId: string, title: string) => Promise<StructureDocument>;
      // Only present on reorderable trees (those with supportsDrag).
      move?: (nodeId: string, parentId: string, index: number) => Promise<StructureDocument>;
      cascadePreview: (nodeId: string) => Promise<StructureNodeDeletePreview>;
      delete: (nodeId: string) => Promise<StructureDocument>;
    };
    openLeaf: (sceneId: string) => Promise<void>;
    onGroupClick: (nodeId: string) => void;
    onGroupDblClick?: (nodeId: string) => void;
    // When true, double-clicking a group row starts an inline rename instead of
    // calling onGroupDblClick (research has no container editor to open).
    groupDblClickRenames?: boolean;
    cascadeLabels: {
      leaf: { singular: string; plural: string };
      container: { singular: string; plural: string };
    };
    afterDelete?: () => Promise<void>;
    afterRename?: (nodeId: string, newTitle: string) => Promise<void>;
    supportsDrag: boolean;
    showStatusStripe: boolean;
    containerHasEditor: boolean;
    inlineRenameOnLeafCreate: boolean;
    rootAddMenuKey: string;
  };
</script>

<script lang="ts">
  import { tick } from "svelte";
  import { api } from "@/lib/api";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import {
    entryTypeChoicesByKind,
    entryTypeName,
    findNewlyAddedChildId,
    findNodeBySceneId,
    findParentAndIndex,
    findStructureNodeById,
    isLeafNode,
    nodeChildren,
    updateNodeTitleInTree,
  } from "@/lib/utils/treeHelpers";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";

  export let config: TreeConfig;
  // Reactive tree data — drives the render. Handlers read config.getStructure()
  // instead (see note on the type) so post-mutation reads aren't stale.
  export let structure: StructureDocument | null;
  export let collapsed: Record<string, boolean>;
  // metadataSchema is global per-project — read it from the store instead of
  // drilling it as a prop (#14 Step 2).
  $: schema = $metadataSchemaStore;
  // Active-row highlight read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  export let draftTitles: Map<string, string>;
  export let sectionLabel: string;
  export let emptyLabel: string;
  // Per-node view color annotations (0.5.0 step 4, #81). Keyed by structure
  // node id → swatch id/hex. App computes these by evaluating the Draft pane's
  // selected view over the flattened structure (color annotations only — the
  // tree keeps its structural shape, ADR-0022). Null/empty on trees without a
  // switcher (Research) or when the default view is selected.
  export let colorAnnotations: Map<string, string | null> | null = null;
  // Membership pruning (#101): the set of structure-node ids to show — the
  // selected view's matches plus the ancestors kept to reach them. `null` = the
  // whole-universe default → show the full tree. A node absent from the set (and
  // therefore all of its descendants) is hidden, narrowing the tree to matches.
  export let visibleIds: Set<string> | null = null;
  // App's error-catching async wrapper. Returns whether the action completed
  // without throwing.
  export let run: (action: () => Promise<void>) => Promise<boolean>;
  // Delete stays in App (it tears down editor panes pointing at the doomed
  // subtree before deleting); this component just requests it.
  export let onRequestDelete: (node: StructureNode) => void;
  // Add-menu state lives in App so a single menu is open across both trees and
  // App's document-level click-outside handler can close it.
  export let addMenuOpenFor: string | null;
  export let addMenuPosition: { top: number; right: number } | null;
  export let onToggleAddMenu: (nodeId: string, event?: MouseEvent) => void;
  export let onCloseAddMenu: () => void;

  // Tree-local UI state — inline rename + drag. Never escapes the component.
  let editingNodeId: string | null = null;
  let editingTitle = "";
  let draggedNodeId: string | null = null;
  let dragOverNodeId: string | null = null;
  let dragOverPosition: "before" | "after" | "into" | null = null;

  // Children to render under `node`, pruned to the selected view's membership
  // (#101). `visibleIds === null` (the default view) shows every child.
  function visibleChildren(node: StructureNode): StructureNode[] {
    const kids = nodeChildren(node);
    return visibleIds ? kids.filter((c) => visibleIds!.has(c.id)) : kids;
  }

  function renderNodeTitle(node: StructureNode): string {
    const template = schema?.entry_types[node.type]?.display_template ?? "{title}";
    const liveTitle = node.scene_id ? draftTitles.get(node.scene_id) : undefined;
    const effectiveTitle = liveTitle ?? node.title;
    return template.replace(/\{(\w+)\}/g, (_match, fieldName) => {
      if (fieldName === "title") return effectiveTitle;
      const computed = node.computed_metadata?.[fieldName];
      if (computed !== undefined && computed !== null) return String(computed);
      return "";
    });
  }

  function nextAutoName(parentId: string | null, entryType: string): string {
    const typeName = entryTypeName(entryType, schema);
    const root = config.getStructure()?.root ?? null;
    const parent = !root ? null : parentId ? findStructureNodeById(root, parentId) : root;
    const siblingCount = parent?.children?.filter((child) => child.type === entryType).length ?? 0;
    return `${typeName} ${siblingCount + 1}`;
  }

  // Generic "+ Add child" creator. Auto-names by sibling count, calls the
  // kind-specific create API, then either drops the user into the editor (leaf)
  // or into an inline tree-row rename (non-leaf). The manuscript-scene leaf
  // takes a legacy path through api.createScene (a pre-structure-node holdover
  // that refreshes via the leaf API and also inline-renames so the
  // auto-generated title can be replaced).
  async function addTreeChild(parentId: string | null, entryType: string) {
    const title = nextAutoName(parentId, entryType);
    onCloseAddMenu();
    await run(async () => {
      const before = config.getStructure();
      let createdNodeId: string | null = null;
      const isLeaf = entryType === config.leafType;
      if (config.kind === "scene" && isLeaf) {
        const scene = await api.createScene(title, parentId ?? undefined);
        await config.refresh();
        await config.openLeaf(scene.id);
        const root = config.getStructure()?.root;
        createdNodeId = root ? findNodeBySceneId(root, scene.id)?.id ?? null : null;
      } else {
        const next = await config.api.create(title, entryType, parentId);
        config.applyStructure(next);
        createdNodeId = findNewlyAddedChildId(before, next, parentId);
        if (createdNodeId && isLeaf) {
          const created = findStructureNodeById(next.root, createdNodeId);
          if (created?.scene_id) {
            await config.openLeaf(created.scene_id);
          }
        }
      }
      if (createdNodeId && (!isLeaf || config.inlineRenameOnLeafCreate)) {
        startRename(createdNodeId, title);
      }
    });
  }

  function startRename(nodeId: string, currentTitle: string) {
    editingNodeId = nodeId;
    editingTitle = currentTitle;
    setTimeout(() => {
      const input = document.querySelector<HTMLInputElement>(`[data-node-edit-id="${nodeId}"]`);
      if (input) {
        input.focus();
        input.select();
      }
    }, 0);
  }

  async function commitRename(nodeId: string) {
    if (editingNodeId !== nodeId) return;
    const trimmed = editingTitle.trim();
    const tree = config.getStructure();
    const node = tree ? findStructureNodeById(tree.root, nodeId) : null;
    editingNodeId = null;
    if (!trimmed || !node || node.title === trimmed) {
      return;
    }
    if (tree) {
      config.applyStructure({ root: updateNodeTitleInTree(tree.root, nodeId, trimmed) });
    }
    await run(async () => {
      const next = await config.api.rename(nodeId, trimmed);
      config.applyStructure(next);
      if (config.afterRename) {
        await config.afterRename(nodeId, trimmed);
      }
    });
  }

  function cancelRename() {
    editingNodeId = null;
  }

  function handleRenameKeydown(event: KeyboardEvent, nodeId: string) {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitRename(nodeId);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
    }
  }

  // Keyboard reorder + F2 rename — only on reorderable trees (manuscript).
  function handleRowKeydown(event: KeyboardEvent, node: StructureNode) {
    if (!config.supportsDrag) return;
    if (event.key === "F2") {
      event.preventDefault();
      startRename(node.id, node.title);
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key === "ArrowUp") {
      event.preventDefault();
      void moveNodeUp(node);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      void moveNodeDown(node);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      void indentNode(node);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      void outdentNode(node);
    }
  }

  function handleGroupDblClick(node: StructureNode) {
    if (config.groupDblClickRenames) {
      startRename(node.id, node.title);
    } else {
      config.onGroupDblClick?.(node.id);
    }
  }

  async function refocusTreeNode(nodeId: string) {
    await tick();
    // Look up the row via NodeRow's data-node-id attribute, then focus the
    // inner click button (NodeRow's default title path) so the focus ring lands
    // on the right element.
    const row = document.querySelector<HTMLElement>(`[data-node-id="${nodeId}"]`);
    const target = row?.querySelector<HTMLElement>("button.node-row-click") ?? row;
    target?.focus();
  }

  async function moveNodeUp(node: StructureNode) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, node.id);
    if (!found || found.index === 0) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(node.id, found.parent.id, found.index - 1));
    });
    await refocusTreeNode(node.id);
  }

  async function moveNodeDown(node: StructureNode) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, node.id);
    if (!found || found.index >= (found.parent.children?.length ?? 0) - 1) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(node.id, found.parent.id, found.index + 1));
    });
    await refocusTreeNode(node.id);
  }

  async function indentNode(node: StructureNode) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, node.id);
    if (!found || found.index === 0) return;
    const previousSibling = found.parent.children[found.index - 1];
    if (previousSibling.scene_id) return;
    const newPosition = previousSibling.children?.length ?? 0;
    await run(async () => {
      config.applyStructure(await config.api.move!(node.id, previousSibling.id, newPosition));
    });
    await refocusTreeNode(node.id);
  }

  async function outdentNode(node: StructureNode) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const parentFound = findParentAndIndex(tree.root, node.id);
    if (!parentFound) return;
    if (parentFound.parent.id === tree.root.id) return;
    const grandparentFound = findParentAndIndex(tree.root, parentFound.parent.id);
    if (!grandparentFound) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(node.id, grandparentFound.parent.id, grandparentFound.index + 1));
    });
    await refocusTreeNode(node.id);
  }

  function handleTreeDragStart(event: DragEvent, node: StructureNode) {
    draggedNodeId = node.id;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", node.id);
    }
  }

  function handleTreeDragEnd() {
    draggedNodeId = null;
    dragOverNodeId = null;
    dragOverPosition = null;
  }

  function handleTreeDragOver(event: DragEvent, node: StructureNode) {
    if (!draggedNodeId || draggedNodeId === node.id) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const ratio = (event.clientY - rect.top) / rect.height;
    let position: "before" | "after" | "into";
    const isContainer = !isLeafNode(node);
    if (isContainer && ratio > 0.2 && ratio < 0.8) {
      position = "into";
    } else if (ratio < 0.5) {
      position = "before";
    } else {
      position = "after";
    }
    if (dragOverNodeId !== node.id || dragOverPosition !== position) {
      dragOverNodeId = node.id;
      dragOverPosition = position;
    }
  }

  async function handleTreeDrop(event: DragEvent, node: StructureNode) {
    event.preventDefault();
    const sourceId = draggedNodeId;
    const position = dragOverPosition;
    handleTreeDragEnd();
    const tree = config.getStructure();
    if (!sourceId || !position || !tree || !config.api.move || sourceId === node.id) return;

    let targetParentId: string;
    let targetIndex: number;
    if (position === "into") {
      targetParentId = node.id;
      const target = findStructureNodeById(tree.root, node.id);
      targetIndex = target?.children?.length ?? 0;
    } else {
      const found = findParentAndIndex(tree.root, node.id);
      if (!found) return;
      targetParentId = found.parent.id;
      targetIndex = found.index + (position === "after" ? 1 : 0);
    }

    const sourceFound = findParentAndIndex(tree.root, sourceId);
    if (sourceFound && sourceFound.parent.id === targetParentId && sourceFound.index < targetIndex) {
      targetIndex -= 1;
    }

    await run(async () => {
      config.applyStructure(await config.api.move!(sourceId, targetParentId, targetIndex));
    });
  }
</script>

<div class="section-title">
  <h3>{sectionLabel}</h3>
  <div class="tree-add-controls">
    <div class="tree-menu-anchor">
      <button class="row-action-add section-add-button" class:active={addMenuOpenFor === config.rootAddMenuKey} title="Add at root" on:click={(event) => onToggleAddMenu(config.rootAddMenuKey, event)}>+&gt;</button>
      {#if addMenuOpenFor === config.rootAddMenuKey}
        <div class="row-add-popover" style={addMenuPosition ? `top: ${addMenuPosition.top}px; right: ${addMenuPosition.right}px` : ""}>
          <span class="row-add-popover-heading">Add at root</span>
          <NodeList isEmpty={false}>
            {#each entryTypeChoicesByKind(schema, config.kind) as choice (choice.id)}
              <NodeRow
                title={choice.name}
                onClick={() => { addTreeChild(null, choice.id); onCloseAddMenu(); }}
              />
            {/each}
          </NodeList>
        </div>
      {/if}
    </div>
  </div>
</div>
<NodeList isEmpty={!structure || nodeChildren(structure.root).length === 0}>
  {#if structure}
    {#each visibleChildren(structure.root) as child (child.id)}
      {@render renderTree(child)}
    {/each}
  {/if}
  {#snippet whenEmpty()}
    {#if !structure}
      <p class="muted">Open or create a project to begin.</p>
    {:else}
      <p class="muted">{emptyLabel}</p>
    {/if}
  {/snippet}
</NodeList>

{#snippet renderTree(node: StructureNode)}
  {@const childNodes = visibleChildren(node)}
  {@const leaf = node.type === config.leafType}
  {@const editing = editingNodeId === node.id}
  {@const collapsedMap = collapsed}
  {@const stripeHex = (() => {
    if (!config.showStatusStripe) return null;
    const opt = node.status ? schema?.fields?.status?.options?.find((o) => o.value === node.status) : null;
    return opt?.color ? getSwatch(opt.color)?.hex ?? null : null;
  })()}
  {@const viewStripeHex = (() => {
    const c = colorAnnotations?.get(node.id) ?? null;
    return c ? getSwatch(c)?.hex ?? null : null;
  })()}
  {@const isActive = (
    (!!node.scene_id && focusedDocument?.type === config.kind && focusedDocument.id === node.scene_id)
    || (config.containerHasEditor && focusedDocument?.type === "structure_node" && focusedDocument.id === node.id)
  )}
  {#if leaf && !editing}
    <!-- Simplest-form leaf NodeRow — same widget as a lore character.
         No status stripe (called out as visual noise on scenes); drag
         handle only on trees that support reorder. -->
    <NodeRow
      role="treeitem"
      ariaLabel={node.title}
      title={renderNodeTitle(node)}
      active={isActive}
      stripeColor={viewStripeHex}
      dragging={config.supportsDrag && draggedNodeId === node.id}
      dropPosition={config.supportsDrag && dragOverNodeId === node.id ? dragOverPosition : null}
      onClick={() => node.scene_id && run(() => config.openLeaf(node.scene_id!))}
      onmousedown={(event) => event.stopPropagation()}
      onkeydown={(event) => handleRowKeydown(event, node)}
      ondragover={(event) => { if (config.supportsDrag) handleTreeDragOver(event, node); }}
      ondrop={(event) => { if (config.supportsDrag) handleTreeDrop(event, node); }}
    >
      {#snippet leading()}
        {#if config.supportsDrag}
          <span
            class="tree-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            on:dragstart={(event) => handleTreeDragStart(event, node)}
            on:dragend={handleTreeDragEnd}
          >⋮⋮</span>
        {/if}
      {/snippet}
    </NodeRow>
  {:else if editing}
    <!-- Rename-in-progress: titleSlot hosts the input. Variant stays
         consistent with the underlying node (card for leaves, tree
         group header for containers) so the row doesn't reflow when
         editing ends. -->
    <NodeRow
      groupHeader={!leaf}
      role="treeitem"
      ariaLabel={node.title}
      stripeColor={viewStripeHex ?? (leaf ? null : stripeHex)}
      dragging={config.supportsDrag && draggedNodeId === node.id}
      dropPosition={config.supportsDrag && dragOverNodeId === node.id ? dragOverPosition : null}
      collapsed={leaf ? true : (!!collapsedMap[node.id] || childNodes.length === 0)}
      clickable={false}
      dataNodeId={node.id}
      onmousedown={(event) => event.stopPropagation()}
      ondragover={(event) => { if (config.supportsDrag) handleTreeDragOver(event, node); }}
      ondrop={(event) => { if (config.supportsDrag) handleTreeDrop(event, node); }}
    >
      {#snippet titleSlot()}
        <input
          class="tree-title tree-rename-input"
          data-node-edit-id={node.id}
          bind:value={editingTitle}
          on:keydown={(event) => handleRenameKeydown(event, node.id)}
          on:blur={() => commitRename(node.id)}
        />
      {/snippet}
      {#snippet nested()}
        {#if !leaf}
          {#each childNodes as child (child.id)}
            {@render renderTree(child)}
          {/each}
        {/if}
      {/snippet}
    </NodeRow>
  {:else}
    <!-- Group-header form (non-leaf). Click toggles collapse (manuscript
         defers to dblclick-open-editor); double-click is config-driven. -->
    {@const isCollapsed = !!collapsedMap[node.id] || childNodes.length === 0}
    <NodeRow
      groupHeader
      role="treeitem"
      ariaLabel={node.title}
      title={renderNodeTitle(node)}
      active={isActive}
      stripeColor={viewStripeHex ?? stripeHex}
      dragging={config.supportsDrag && draggedNodeId === node.id}
      dropPosition={config.supportsDrag && dragOverNodeId === node.id ? dragOverPosition : null}
      collapsed={isCollapsed}
      dataNodeId={node.id}
      onClick={() => config.onGroupClick(node.id)}
      onDblClick={() => handleGroupDblClick(node)}
      onmousedown={(event) => event.stopPropagation()}
      onkeydown={(event) => handleRowKeydown(event, node)}
      ondragover={(event) => { if (config.supportsDrag) handleTreeDragOver(event, node); }}
      ondrop={(event) => { if (config.supportsDrag) handleTreeDrop(event, node); }}
    >
      {#snippet leading()}
        {#if config.supportsDrag}
          <span
            class="tree-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            on:dragstart={(event) => handleTreeDragStart(event, node)}
            on:dragend={handleTreeDragEnd}
          >⋮⋮</span>
        {/if}
        <GroupCaret collapsed={isCollapsed} />
      {/snippet}
      {#snippet trailing()}
        <CountPill count={childNodes.length} />
        <div class="tree-menu-anchor">
          <button class="row-action-add" class:active={addMenuOpenFor === node.id} title="Add child" on:click|stopPropagation={(event) => onToggleAddMenu(node.id, event)}>+&gt;</button>
          {#if addMenuOpenFor === node.id}
            <div class="row-add-popover" style={addMenuPosition ? `top: ${addMenuPosition.top}px; right: ${addMenuPosition.right}px` : ""}>
              <span class="row-add-popover-heading">Add child</span>
              <NodeList isEmpty={false}>
                {#each entryTypeChoicesByKind(schema, config.kind) as choice (choice.id)}
                  <NodeRow
                    title={choice.name}
                    onClick={() => { addTreeChild(node.id, choice.id); onCloseAddMenu(); }}
                  />
                {/each}
              </NodeList>
            </div>
          {/if}
        </div>
        <button class="row-action-delete" title={`Delete ${entryTypeName(node.type, schema)}`} on:click|stopPropagation={() => { if (editingNodeId === node.id) editingNodeId = null; onRequestDelete(node); }}>×</button>
      {/snippet}
      {#snippet nested()}
        {#each childNodes as child (child.id)}
          {@render renderTree(child)}
        {/each}
      {/snippet}
    </NodeRow>
  {/if}
{/snippet}

<style>
  /* Tree-pane chrome co-located from styles.css (#14). The shared row
     framework (.tree-row* / .tree-handle* drag vocab) and shared utilities
     (button.row-action-add) stay global. App.svelte `closest()`-queries
     .tree-menu-anchor / .row-add-popover by class name only — scoping keeps
     the class, so outside-click detection is unaffected. */
  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .tree-rename-input {
    flex: 1;
    min-width: 0;
    padding: 2px 6px;
    font-size: var(--fs-md);
    border: 1px solid var(--accent);
    border-radius: 4px;
    background: var(--surface);
  }

  .tree-add-controls {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  /* .tree-menu-anchor / .row-add-popover / .row-add-popover-heading are now
     global in styles.css — shared with the Lore "+ Entry" type-picker (#67). */
</style>
