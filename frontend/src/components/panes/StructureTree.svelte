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
  import { onDestroy } from "svelte";
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

  let {
    config,
    structure,
    viewSpec,
    sectionLabel,
    emptyLabel,
    draftTitles,
    run,
    onRequestDelete,
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

  // Drag + inline-rename state now live in the wrapper (ViewNodeList owns the
  // gesture + edit state; 4c-i/iii). We keep a handle to it for the two rename
  // triggers that originate OUTSIDE a row render — create-then-rename and
  // cancel-on-delete — plus the local collapse defer-guard.
  let list = $state<{
    beginRename: (id: string, title: string) => void;
    cancelRename: (id: string) => void;
    toggleAddMenu: (parentId: string | null, key: string, event?: MouseEvent) => void;
    isAddMenuOpen: (key: string) => boolean;
  }>();

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
        list?.beginRename(createdNodeId, title);
      }
    });
  }

  // Persist a committed inline rename. ViewNodeList owns the edit state + guards
  // and only calls this for a real change; we do the optimistic update + API write.
  async function domainRename(node: EvalNode, nextTitle: string) {
    const tree = config.getStructure();
    const sn = tree ? findStructureNodeById(tree.root, node.id) : null;
    if (!tree || !sn || sn.title === nextTitle) return;
    config.applyStructure({ root: updateNodeTitleInTree(tree.root, node.id, nextTitle) });
    await run(async () => {
      const next = await config.api.rename(node.id, nextTitle);
      config.applyStructure(next);
      if (config.afterRename) {
        await config.afterRename(node.id, nextTitle);
      }
    });
  }

  // Container double-click: manuscript opens the structure-node editor, research
  // renames inline (via the wrapper's imperative beginRename). The wrapper cancels
  // the pending collapse (defer-guard) before invoking this.
  function handleGroupDblClick(node: EvalNode) {
    if (config.groupDblClickRenames) {
      list?.beginRename(node.id, node.title);
    } else {
      config.onGroupDblClick?.(node.id);
    }
  }

  function requestDelete(node: EvalNode) {
    list?.cancelRename(node.id);
    const root = config.getStructure()?.root;
    const sn = root ? findStructureNodeById(root, node.id) : null;
    if (sn) onRequestDelete(sn);
  }

  // The domain half of reorder: ViewNodeList owns the gesture + keyboard and hands us
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
        class:active={list?.isAddMenuOpen(config.rootAddMenuKey) ?? false}
        title="Add at root"
        aria-label="Add at root"
        onclick={(event) => list?.toggleAddMenu(null, config.rootAddMenuKey, event)}
      >+</button>
    </div>
  </div>
</div>

<ViewNodeList
  bind:this={list}
  {result}
  mode="tree"
  active={isActiveNode}
  collapsed={collapse.collapsed}
  onReorder={config.supportsDrag ? handleReorder : undefined}
  isContainer={(node) => node.entry_type !== config.leafType}
  onRename={domainRename}
  onDblClick={handleGroupDblClick}
  {row}
  {addMenu}
>
  {#snippet whenEmpty()}
    {#if !structure}
      <p class="muted">Open or create a project to begin.</p>
    {:else}
      <p class="muted">{emptyLabel}</p>
    {/if}
  {/snippet}
</ViewNodeList>

{#snippet addMenu({ parentId, close }: { parentId: string | null; close: () => void })}
  <span class="row-add-popover-heading">{parentId === null ? "Add at root" : "Add child"}</span>
  <NodeList isEmpty={false}>
    {#each entryTypeChoicesByKind(schema, config.kind) as choice (choice.id)}
      <NodeRow title={choice.name} onClick={() => { addTreeChild(parentId, choice.id); close(); }} />
    {/each}
  </NodeList>
{/snippet}

{#snippet row(node: EvalNode, ctx: RowCtx<EvalNode>)}
  {@const leaf = node.entry_type === config.leafType}
  {@const editing = ctx.editing}
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
          value={ctx.editValue}
          oninput={(event) => ctx.onEditInput(event.currentTarget.value)}
          onblur={ctx.commitRename}
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
      onClick={ctx.toggleCollapse}
      onDblClick={ctx.onDblClick}
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
            class:active={ctx.addMenuOpen}
            title="Add child"
            aria-label="Add child"
            onclick={(event) => { event.stopPropagation(); ctx.toggleAddMenu(event); }}
          >+</button>
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
</style>
