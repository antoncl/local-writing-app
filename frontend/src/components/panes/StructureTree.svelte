<script module lang="ts">
  import type { StructureDocument, StructureNode, StructureNodeDeletePreview } from "@/lib/types";

  // Per-kind tree config. The manuscript and research panes both render
  // hierarchical trees with the same leaf/container shape; the only differences
  // (drag, status stripe, leaf-open API, cascade-preview labels, etc.) live here
  // so one component serves both. App owns the structure data + editor-pane
  // coupling (delete, dblclick-open); this component owns the rendering (now via
  // ViewNodeList, #112) and the inline CRUD (add / rename / drag-reorder).
  //
  // Collapse is NO LONGER in this config: it moved onto ViewNodeList's own
  // per-group set (#182 substrate). `onGroupClick` (the old collapse toggle) is
  // gone with it; `onGroupDblClick` stays (open the container editor).
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
    // Double-click on a container row. Manuscript opens the structure-node
    // editor; research has none, so it falls through to an inline rename
    // (groupDblClickRenames).
    onGroupDblClick?: (nodeId: string) => void;
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
    // Persist per-view collapse to the backend `/ui` endpoint (ADR-0036). True
    // for the explicit Draft pane; false for Research (its collapse is ephemeral
    // until implicit host-node fold state lands, memo §2).
    persistCollapse: boolean;
  };
</script>

<script lang="ts">
  import { tick, onDestroy } from "svelte";
  import { api } from "@/lib/api";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import {
    entryTypeChoicesByKind,
    entryTypeName,
    findNewlyAddedChildId,
    findNodeBySceneId,
    findParentAndIndex,
    findStructureNodeById,
    updateNodeTitleInTree,
  } from "@/lib/utils/treeHelpers";
  import { structureToEvalNodes } from "@/lib/views/structureNodes";
  import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";
  import type { ViewSpec } from "@/lib/types";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { CollapseState } from "@/lib/stores/collapseState.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import { referenceIndexStore } from "@/lib/stores/references";

  // Single-click on a container defers collapse past the double-click window so
  // a fast second click can cancel it and open the editor instead (without the
  // defer the row visibly toggles for ~100ms before the editor opens on top).
  const DBLCLICK_GUARD_MS = 200;

  let {
    config,
    structure,
    viewSpec,
    sectionLabel,
    emptyLabel,
    draftTitles,
    run,
    onRequestDelete,
    addMenuOpenFor,
    addMenuPosition,
    onToggleAddMenu,
    onCloseAddMenu,
  }: {
    config: TreeConfig;
    // Reactive tree data — feeds the view evaluation. Handlers read
    // config.getStructure() instead so post-mutation reads aren't stale.
    structure: StructureDocument | null;
    // The pane's selected view spec. Draft only ever renders a tree + tints
    // (ADR-0022), so we force `presentation: "tree"`; the spec's expr/handles
    // still drive membership pruning + color annotations.
    viewSpec: ViewSpec;
    draftTitles: Map<string, string>;
    sectionLabel: string;
    emptyLabel: string;
    // App's error-catching async wrapper. Returns whether the action completed.
    run: (action: () => Promise<void>) => Promise<boolean>;
    // Delete stays in App (it tears down editor panes pointing at the doomed
    // subtree first); this component just looks the node up and requests it.
    onRequestDelete: (node: StructureNode) => void;
    // Add-menu state lives in App so a single menu is shared across both trees
    // and App's document-level click-outside handler can close it.
    addMenuOpenFor: string | null;
    addMenuPosition: { top: number; right: number } | null;
    onToggleAddMenu: (nodeId: string, event?: MouseEvent) => void;
    onCloseAddMenu: () => void;
  } = $props();

  // Globals read from stores rather than drilled as props (#14 Step 2).
  const schema = $derived($metadataSchemaStore);
  const focusedDocument = $derived($focusedDocumentStore);
  const referenceIndex = $derived($referenceIndexStore);

  // One evaluation feeds the whole render: tree shape (via the `ancestry`
  // side-channel), membership pruning, and color annotations — replacing the
  // App-side double-eval this migration deleted (#112). Forced to a tree because
  // the Draft/Research panes only ever tint, never re-shape (ADR-0022).
  const result = $derived(
    evaluateView({ ...viewSpec, presentation: "tree" }, structureToEvalNodes(structure), {
      schema,
      resolveView: paneViews.resolveView,
      referenceIndex,
    }),
  );

  // Per-view collapse persistence (ADR-0036). The controller's set is bound into
  // ViewNodeList; for the explicit Draft pane we seed/persist it against the
  // pane's resolved view id (selected saved view, or `view_default_<kind>`).
  // Research (persistCollapse=false) never binds → the same set stays ephemeral.
  const collapse = new CollapseState();
  const resolvedViewId = $derived(paneViews.resolvedViewId(config.kind));
  $effect(() => {
    if (config.persistCollapse) void collapse.bind(resolvedViewId);
  });
  $effect(() => {
    if (config.persistCollapse) collapse.observe();
  });
  onDestroy(() => {
    if (config.persistCollapse) void collapse.flush();
  });

  // Tree-local UI state — inline rename + the collapse defer-guard. Drag state
  // now lives in the wrapper (ViewNodeList owns the gesture; 4c-i). Never escapes.
  let editingNodeId = $state<string | null>(null);
  let editingTitle = $state("");
  let pendingCollapseTimeout: ReturnType<typeof setTimeout> | null = null;

  function isActiveNode(node: EvalNode): boolean {
    return (
      (!!node.ref_id && focusedDocument?.type === config.kind && focusedDocument.id === node.ref_id) ||
      (config.containerHasEditor &&
        focusedDocument?.type === "structure_node" &&
        focusedDocument.id === node.id)
    );
  }

  function statusHex(node: EvalNode): string | null {
    if (!config.showStatusStripe) return null;
    const status = node.metadata?.status;
    if (typeof status !== "string") return null;
    const opt = schema?.fields?.status?.options?.find((o) => o.value === status);
    return opt?.color ? getSwatch(opt.color)?.hex ?? null : null;
  }

  function renderNodeTitle(node: EvalNode): string {
    const template = schema?.entry_types[node.entry_type]?.display_template ?? "{title}";
    const liveTitle = node.ref_id ? draftTitles.get(node.ref_id) : undefined;
    const effectiveTitle = liveTitle ?? node.title;
    return template.replace(/\{(\w+)\}/g, (_match, fieldName) => {
      if (fieldName === "title") return effectiveTitle;
      const computed = node.metadata?.[fieldName];
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
  // or an inline tree-row rename (non-leaf). The manuscript-scene leaf takes a
  // legacy path through api.createScene that refreshes via the leaf API.
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
  function handleRowKeydown(event: KeyboardEvent, nodeId: string) {
    if (!config.supportsDrag) return;
    if (event.key === "F2") {
      event.preventDefault();
      const root = config.getStructure()?.root;
      const sn = root ? findStructureNodeById(root, nodeId) : null;
      startRename(nodeId, sn?.title ?? "");
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key === "ArrowUp") {
      event.preventDefault();
      void moveNodeUp(nodeId);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      void moveNodeDown(nodeId);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      void indentNode(nodeId);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      void outdentNode(nodeId);
    }
  }

  // All tree keyboard handling rides on ONE direct listener on the list
  // wrapper, dispatched by the event target's data-node markers. Svelte 5
  // DELEGATES keydown at a per-component boundary, and the `row` snippet's DOM
  // (owned here, mounted inside ViewNodeTree) falls outside StructureTree's
  // delegation root — so per-element `onkeydown` props silently never fire
  // (click/blur, which are non-delegated here, still work). A direct
  // addEventListener sidesteps delegation entirely. (#112 — the #182 substrate's
  // first keydown consumer; the wrapper-owned version lands in phase 1b.)
  function treeKeyboard(container: HTMLElement) {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      // Keys typed inside an add-child popover are the popover's own (its
      // buttons); don't let Ctrl+arrows there reorder the hosting container.
      if (target.closest(".row-add-popover")) return;
      const input = target.closest<HTMLElement>("[data-node-edit-id]");
      if (input) {
        handleRenameKeydown(event, input.getAttribute("data-node-edit-id") ?? "");
        return;
      }
      const row = target.closest<HTMLElement>("[data-node-id]");
      const id = row?.getAttribute("data-node-id");
      if (id) handleRowKeydown(event, id);
    };
    container.addEventListener("keydown", onKey);
    return { destroy: () => container.removeEventListener("keydown", onKey) };
  }

  // Container click defers collapse (see DBLCLICK_GUARD_MS); the toggle itself
  // is ViewNodeList's, handed in via RowCtx.
  function deferCollapse(toggle: () => void) {
    if (pendingCollapseTimeout !== null) clearTimeout(pendingCollapseTimeout);
    pendingCollapseTimeout = setTimeout(() => {
      pendingCollapseTimeout = null;
      toggle();
    }, DBLCLICK_GUARD_MS);
  }

  function handleGroupDblClick(node: EvalNode) {
    if (pendingCollapseTimeout !== null) {
      clearTimeout(pendingCollapseTimeout);
      pendingCollapseTimeout = null;
    }
    if (config.groupDblClickRenames) {
      startRename(node.id, node.title);
    } else {
      config.onGroupDblClick?.(node.id);
    }
  }

  function requestDelete(node: EvalNode) {
    if (editingNodeId === node.id) editingNodeId = null;
    const root = config.getStructure()?.root;
    const sn = root ? findStructureNodeById(root, node.id) : null;
    if (sn) onRequestDelete(sn);
  }

  async function refocusTreeNode(nodeId: string) {
    await tick();
    const row = document.querySelector<HTMLElement>(`[data-node-id="${nodeId}"]`);
    const target = row?.querySelector<HTMLElement>("button.node-row-click") ?? row;
    target?.focus();
  }

  async function moveNodeUp(nodeId: string) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, nodeId);
    if (!found || found.index === 0) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(nodeId, found.parent.id, found.index - 1));
    });
    await refocusTreeNode(nodeId);
  }

  async function moveNodeDown(nodeId: string) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, nodeId);
    if (!found || found.index >= (found.parent.children?.length ?? 0) - 1) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(nodeId, found.parent.id, found.index + 1));
    });
    await refocusTreeNode(nodeId);
  }

  async function indentNode(nodeId: string) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const found = findParentAndIndex(tree.root, nodeId);
    if (!found || found.index === 0) return;
    const previousSibling = found.parent.children[found.index - 1];
    if (previousSibling.scene_id) return;
    const newPosition = previousSibling.children?.length ?? 0;
    await run(async () => {
      config.applyStructure(await config.api.move!(nodeId, previousSibling.id, newPosition));
    });
    await refocusTreeNode(nodeId);
  }

  async function outdentNode(nodeId: string) {
    const tree = config.getStructure();
    if (!tree || !config.api.move) return;
    const parentFound = findParentAndIndex(tree.root, nodeId);
    if (!parentFound) return;
    if (parentFound.parent.id === tree.root.id) return;
    const grandparentFound = findParentAndIndex(tree.root, parentFound.parent.id);
    if (!grandparentFound) return;
    await run(async () => {
      config.applyStructure(await config.api.move!(nodeId, grandparentFound.parent.id, grandparentFound.index + 1));
    });
    await refocusTreeNode(nodeId);
  }

  // The domain half of drag-reorder: ViewNodeList owns the gesture and hands us
  // the settled (moved, target, position) intent; we translate it to a
  // parent/index and call the move API. `into` drops append under the target;
  // before/after resolve against the target's parent, with the usual same-parent
  // index adjustment when the source sat before the drop slot.
  async function handleReorder(
    moved: EvalNode,
    target: EvalNode,
    position: "before" | "after" | "into",
  ) {
    const tree = config.getStructure();
    if (!tree || !config.api.move || moved.id === target.id) return;

    let targetParentId: string;
    let targetIndex: number;
    if (position === "into") {
      targetParentId = target.id;
      const container = findStructureNodeById(tree.root, target.id);
      targetIndex = container?.children?.length ?? 0;
    } else {
      const found = findParentAndIndex(tree.root, target.id);
      if (!found) return;
      targetParentId = found.parent.id;
      targetIndex = found.index + (position === "after" ? 1 : 0);
    }

    const sourceFound = findParentAndIndex(tree.root, moved.id);
    if (sourceFound && sourceFound.parent.id === targetParentId && sourceFound.index < targetIndex) {
      targetIndex -= 1;
    }

    await run(async () => {
      config.applyStructure(await config.api.move!(moved.id, targetParentId, targetIndex));
    });
  }
</script>

<div class="section-title">
  <h3>{sectionLabel}</h3>
  <div class="tree-add-controls">
    <div class="tree-menu-anchor">
      <button
        class="row-action-add section-add-button"
        class:active={addMenuOpenFor === config.rootAddMenuKey}
        title="Add at root"
        aria-label="Add at root"
        onclick={(event) => onToggleAddMenu(config.rootAddMenuKey, event)}
      >+</button>
      {#if addMenuOpenFor === config.rootAddMenuKey}
        <div class="row-add-popover" style={addMenuPosition ? `top: ${addMenuPosition.top}px; right: ${addMenuPosition.right}px` : ""}>
          <span class="row-add-popover-heading">Add at root</span>
          <NodeList isEmpty={false}>
            {#each entryTypeChoicesByKind(schema, config.kind) as choice (choice.id)}
              <NodeRow title={choice.name} onClick={() => { addTreeChild(null, choice.id); onCloseAddMenu(); }} />
            {/each}
          </NodeList>
        </div>
      {/if}
    </div>
  </div>
</div>

<div class="tree-keys" use:treeKeyboard>
  <ViewNodeList
    {result}
    mode="tree"
    active={isActiveNode}
    collapsed={collapse.collapsed}
    onReorder={config.supportsDrag ? handleReorder : undefined}
    isContainer={(node) => node.entry_type !== config.leafType}
    {row}
  >
    {#snippet whenEmpty()}
      {#if !structure}
        <p class="muted">Open or create a project to begin.</p>
      {:else}
        <p class="muted">{emptyLabel}</p>
      {/if}
    {/snippet}
  </ViewNodeList>
</div>

{#snippet row(node: EvalNode, ctx: RowCtx<EvalNode>)}
  {@const leaf = node.entry_type === config.leafType}
  {@const editing = editingNodeId === node.id}
  {@const dragging = ctx.dragging}
  {@const dropPosition = ctx.dropPosition}
  {@const stripe = leaf ? ctx.stripeColor : ctx.stripeColor ?? statusHex(node)}
  {#if editing}
    <!-- Rename-in-progress: titleSlot hosts the input. groupHeader stays true
         for containers so the row keeps its shape while editing. Children (for
         a container) continue to render below via ViewNodeTree recursion. -->
    <NodeRow
      groupHeader={!leaf}
      role="treeitem"
      ariaLabel={node.title}
      depth={ctx.depth}
      stripeColor={stripe}
      {dragging}
      {dropPosition}
      collapsed={ctx.collapsed}
      clickable={false}
      dataNodeId={node.id}
      onmousedown={(event) => event.stopPropagation()}
      ondragover={ctx.reorder?.onDragOver}
      ondrop={ctx.reorder?.onDrop}
    >
      {#snippet titleSlot()}
        <input
          class="tree-title tree-rename-input"
          data-node-edit-id={node.id}
          bind:value={editingTitle}
          onblur={() => commitRename(node.id)}
        />
      {/snippet}
    </NodeRow>
  {:else if leaf}
    <!-- Simplest-form leaf NodeRow — same widget as a lore character. No status
         stripe (visual noise on scenes); drag handle only when reorderable. -->
    <NodeRow
      role="treeitem"
      ariaLabel={node.title}
      title={renderNodeTitle(node)}
      depth={ctx.depth}
      active={ctx.active}
      stripeColor={stripe}
      dataNodeId={node.id}
      {dragging}
      {dropPosition}
      onClick={() => node.ref_id && run(() => config.openLeaf(node.ref_id!))}
      onmousedown={(event) => event.stopPropagation()}
      ondragover={ctx.reorder?.onDragOver}
      ondrop={ctx.reorder?.onDrop}
    >
      {#snippet leading()}
        {#if ctx.reorder}
          <span
            class="tree-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            ondragstart={ctx.reorder.onDragStart}
            ondragend={ctx.reorder.onDragEnd}
          >⋮⋮</span>
        {/if}
      {/snippet}
    </NodeRow>
  {:else}
    <!-- Container (real-node parent). Single click defers collapse to
         RowCtx.toggle; double-click opens the editor (or renames). Children
         recurse below via ViewNodeTree, indented by depth. -->
    <NodeRow
      groupHeader
      role="treeitem"
      ariaLabel={node.title}
      title={renderNodeTitle(node)}
      depth={ctx.depth}
      active={ctx.active}
      stripeColor={stripe}
      collapsed={ctx.collapsed}
      dataNodeId={node.id}
      {dragging}
      {dropPosition}
      onClick={() => deferCollapse(ctx.toggle)}
      onDblClick={() => handleGroupDblClick(node)}
      onmousedown={(event) => event.stopPropagation()}
      ondragover={ctx.reorder?.onDragOver}
      ondrop={ctx.reorder?.onDrop}
    >
      {#snippet leading()}
        {#if ctx.reorder}
          <span
            class="tree-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            ondragstart={ctx.reorder.onDragStart}
            ondragend={ctx.reorder.onDragEnd}
          >⋮⋮</span>
        {/if}
        {#if ctx.collapsible}
          <GroupCaret collapsed={ctx.collapsed} />
        {/if}
      {/snippet}
      {#snippet trailing()}
        <!-- childCount is subtree leaf members; a childless container's
             subtreeCount counts itself (1), so show 0 when not collapsible. -->
        <CountPill count={ctx.collapsible ? ctx.childCount : 0} />
        <div class="tree-menu-anchor">
          <button
            class="row-action-add"
            class:active={addMenuOpenFor === node.id}
            title="Add child"
            aria-label="Add child"
            onclick={(event) => { event.stopPropagation(); onToggleAddMenu(node.id, event); }}
          >+</button>
          {#if addMenuOpenFor === node.id}
            <div class="row-add-popover" style={addMenuPosition ? `top: ${addMenuPosition.top}px; right: ${addMenuPosition.right}px` : ""}>
              <span class="row-add-popover-heading">Add child</span>
              <NodeList isEmpty={false}>
                {#each entryTypeChoicesByKind(schema, config.kind) as choice (choice.id)}
                  <NodeRow title={choice.name} onClick={() => { addTreeChild(node.id, choice.id); onCloseAddMenu(); }} />
                {/each}
              </NodeList>
            </div>
          {/if}
        </div>
        <button
          class="row-action-delete"
          title={`Delete ${entryTypeName(node.entry_type, schema)}`}
          onclick={(event) => { event.stopPropagation(); requestDelete(node); }}
        >×</button>
      {/snippet}
    </NodeRow>
  {/if}
{/snippet}

<style>
  /* Tree-pane chrome co-located from styles.css (#14). The shared row framework
     (.tree-handle drag vocab) and shared utilities (button.row-action-add) stay
     global. App.svelte `closest()`-queries .tree-menu-anchor / .row-add-popover
     by class name only — scoping keeps the class, so outside-click detection is
     unaffected. */
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

  /* Transparent to layout — exists only to host the direct keydown listener
     (see treeKeyboard) around the list. */
  .tree-keys {
    display: contents;
  }
</style>
