<!--
  ViewBodyView — the body-region slot for the `view` kind (0.5.0 step 3, #80).
  A Svelte Flow DAG that authors a ViewSpec's set-algebra expression, with a
  live preview of the result beside the canvas. Owns the ViewSpec state and
  persists it directly via PUT /api/views (mirroring the chat precedent —
  saveEditorPane is a no-op for views); the shell (NodeEditor) owns the title
  and feeds edits in through setTitleFromPane.

  Governing: doc §4, ADR-0018 (Venn-glyph graph), ADR-0019 (annotate). Graph ⇄
  ViewExpr serialization lives in lib/views/viewGraph.ts; evaluation reuses the
  step-2 evaluateView.
-->
<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import { SvelteFlow, Background, Controls, type ColorMode, type Node, type Edge } from "@xyflow/svelte";
  import { untrack } from "svelte";
  import { themePreference } from "@/lib/utils/theme";
  import ViewFlowNode from "./view/ViewFlowNode.svelte";
  import FitView from "./view/FitView.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import { setDesignerContext, type DesignerContext } from "./view/designerContext";
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";
  import { structureToEvalNodes } from "@/lib/views/structureNodes";
  import {
    specToGraph,
    graphToSpec,
    inputArity,
    wouldCycle,
    OUTPUT_NODE_ID,
    type GraphNodeKind,
    type ViewGraph,
    type ViewNodeData,
  } from "@/lib/views/viewGraph";
  import type {
    AssistantEntrySummary,
    EditableDocument,
    LoreEntrySummary,
    MetadataFieldDefinition,
    PromptEntrySummary,
    StructureDocument,
    ViewLayout,
    ViewNode,
    ViewSort,
    ViewSpec,
  } from "@/lib/types";

  interface Props {
    scene?: EditableDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    assistantEntries?: AssistantEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    onBodyChange?: () => void;
    onFocus?: () => void;
  }
  let {
    scene = null,
    loreEntries = [],
    promptEntries = [],
    assistantEntries = [],
    structure = null,
    researchStructure = null,
    onBodyChange,
    onFocus,
  }: Props = $props();

  let schema = $derived($metadataSchemaStore);
  // Svelte Flow ships light-only chrome; drive its theme from the app's. The
  // preference values ("system"/"light"/"dark") map straight to ColorMode.
  let colorMode = $derived($themePreference as ColorMode);

  // The view node's editable state. `title` is fed from the pane header.
  let loadedViewId = $state<string | null>(null);
  let revision = $state("");
  let title = $state("");
  let kind = $state("lore");
  let sort = $state<ViewSort>({ by: "manual" });
  let presentation = $state<ViewNode["presentation"]>("flat");

  // Svelte Flow graph — the source of truth for the expression, bound to the
  // canvas. Custom nodes all use the single "viewNode" type; data carries the
  // graph kind + its config.
  type FlowData = { kind: GraphNodeKind; cfg: ViewNodeData };
  let flowNodes = $state<Node<FlowData>[]>([]);
  let flowEdges = $state<Edge[]>([]);
  const nodeTypes = { viewNode: ViewFlowNode };

  let addCounter = 0;
  let hydrating = false;

  // Saved views of the same kind (for the view_ref leaf + preview resolution).
  let savedViews = $state<{ id: string; title: string }[]>([]);
  // $state so the `preview` derived re-resolves view_ref leaves once the specs
  // finish loading async (mirrors paneViews.svelte.ts); a plain `let` leaves the
  // reassignment untracked and the preview shows referenced views as empty.
  let viewSpecs = $state(new Map<string, ViewSpec>());

  // ---- hydrate from the opened view node ----
  $effect(() => {
    const node = scene as ViewNode | null;
    const id = node?.id ?? null;
    if (!node || !("spec" in node)) return;
    if (id === untrack(() => loadedViewId)) return;
    hydrating = true;
    loadedViewId = id;
    revision = node.revision ?? "";
    title = node.title ?? "";
    kind = node.spec?.kind ?? "lore";
    sort = node.spec?.sort ?? { by: "manual" };
    presentation = node.presentation ?? "flat";
    // Prefer the persisted designer layout (exact positions the author left);
    // fall back to laying out the semantic expr for designer-less / legacy views.
    // Handle ids are explicit so Svelte Flow renders these edges once the new
    // nodes' handle bounds are measured (its layout pass is a derived that
    // recomputes after measurement — no manual defer needed).
    const graph = hydrateGraph(node);
    flowNodes = graph.nodes;
    flowEdges = graph.edges;
    void loadSavedViews(kind, id);
    // Let the derived spec settle before re-enabling persistence.
    queueMicrotask(() => (hydrating = false));
  });

  function toFlowNode(id: string, k: GraphNodeKind, cfg: ViewNodeData, position: { x: number; y: number }): Node<FlowData> {
    return { id, type: "viewNode", position, data: { kind: k, cfg }, deletable: k !== "output" };
  }

  // Build the canvas graph for a view: from its persisted designer `layout`
  // (author's exact positions + wiring) when present, else auto-laid-out from
  // the semantic `expr` (designer-less / legacy / backend-authored views).
  function hydrateGraph(node: ViewNode): { nodes: Node<FlowData>[]; edges: Edge[] } {
    const layout = node.layout;
    if (layout && layout.nodes.length > 0) {
      return {
        nodes: layout.nodes.map((n) =>
          toFlowNode(n.id, n.kind as GraphNodeKind, (n.cfg ?? {}) as ViewNodeData, n.position),
        ),
        edges: layout.edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          sourceHandle: e.source_handle ?? undefined,
          targetHandle: e.target_handle ?? undefined,
        })),
      };
    }
    const g = specToGraph(node.spec);
    return {
      nodes: g.nodes.map((n) => toFlowNode(n.id, n.kind, n.data, n.position)),
      edges: g.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? undefined,
        targetHandle: e.targetHandle ?? undefined,
      })),
    };
  }

  // Serialize the live canvas (positions + wiring) for persistence. Parallel to
  // toGraph()/graphToExpr, but lossless — keeps every node incl. unwired ones,
  // their positions, and full edge handles, none of which survive the semantic
  // expr round-trip.
  function toLayout(): ViewLayout {
    return {
      nodes: flowNodes.map((n) => ({
        id: n.id,
        kind: n.data.kind,
        position: n.position,
        cfg: (n.data.cfg ?? {}) as Record<string, unknown>,
      })),
      edges: flowEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        source_handle: e.sourceHandle ?? null,
        target_handle: e.targetHandle ?? null,
      })),
    };
  }

  async function loadSavedViews(forKind: string, selfId: string | null): Promise<void> {
    try {
      const list = await api.listViews();
      const same = list.entries.filter((v) => v.view_kind === forKind && v.id !== selfId);
      savedViews = same.map((v) => ({ id: v.id, title: v.title }));
      // Prefetch specs so the preview can resolve view_ref leaves synchronously.
      const specs = await Promise.all(same.map((v) => api.getView(v.id).then((n) => [v.id, n.spec] as const).catch(() => null)));
      const map = new Map<string, ViewSpec>();
      for (const entry of specs) if (entry) map.set(entry[0], entry[1]);
      viewSpecs = map;
    } catch {
      savedViews = [];
    }
  }

  // ---- graph → spec ----
  function toGraph(): ViewGraph {
    return {
      nodes: flowNodes.map((n) => ({ id: n.id, kind: n.data.kind, position: n.position, data: n.data.cfg ?? {} })),
      edges: flowEdges.map((e) => ({ id: e.id, source: e.source, target: e.target, targetHandle: e.targetHandle ?? null })),
    };
  }
  let spec = $derived<ViewSpec>(graphToSpec(toGraph(), { kind, sort }));

  // ---- preview universe for the anchor kind ----
  let universe = $derived<EvalNode[]>(universeFor(kind));
  function universeFor(k: string): EvalNode[] {
    if (k === "lore") return loreEntries;
    if (k === "assistant") return assistantEntries;
    if (k === "prompt") return promptEntries;
    if (k === "scene") return structureToEvalNodes(structure);
    return [];
  }
  let preview = $derived(
    evaluateView(spec, universe, {
      schema,
      resolveView: (viewId: string) => viewSpecs.get(viewId) ?? null,
    }),
  );

  // ---- schema-derived leaf-config options for the current kind ----
  let entryTypeOptions = $derived(
    Object.entries(schema?.entry_types ?? {})
      .filter(([, def]) => def.kind === kind && !def.abstract)
      .map(([fqn, def]) => ({ fqn, name: def.name })),
  );
  let fieldOptions = $derived(buildFieldOptions());
  function buildFieldOptions(): { key: string; name: string; def: MetadataFieldDefinition }[] {
    const keys = new Set<string>();
    for (const [, def] of Object.entries(schema?.entry_types ?? {})) {
      if (def.kind !== kind) continue;
      for (const fk of def.fields ?? []) keys.add(fk);
    }
    const out: { key: string; name: string; def: MetadataFieldDefinition }[] = [];
    for (const k of keys) {
      const def = schema?.fields?.[k];
      if (def) out.push({ key: k, name: def.name ?? k, def });
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
  }
  // Tags present in this kind's universe (contextual — avoids a separate store).
  let tagOptions = $derived(collectTags(universe));
  function collectTags(nodes: EvalNode[]): string[] {
    const set = new Set<string>();
    for (const n of nodes) {
      const raw = n.metadata?.tags;
      const arr = Array.isArray(raw) ? raw : typeof raw === "string" ? raw.split(",") : [];
      for (const t of arr) {
        const v = String(t).trim();
        if (v) set.add(v);
      }
    }
    return [...set].sort();
  }

  // ---- designer context for the custom nodes ----
  setDesignerContext(
    (): DesignerContext => ({
      updateNodeData,
      removeNode,
      kind,
      entryTypes: entryTypeOptions,
      fields: fieldOptions,
      fieldByKey: (key: string) => schema?.fields?.[key] ?? null,
      tags: tagOptions,
      savedViews,
      loreEntries,
      promptEntries,
      assistantEntries,
      structure,
      researchStructure,
    }),
  );

  function updateNodeData(id: string, patch: Partial<ViewNodeData>): void {
    flowNodes = flowNodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, cfg: { ...n.data.cfg, ...patch } } } : n));
  }
  function removeNode(id: string): void {
    if (id === OUTPUT_NODE_ID) return;
    flowNodes = flowNodes.filter((n) => n.id !== id);
    flowEdges = flowEdges.filter((e) => e.source !== id && e.target !== id);
  }

  // ---- palette (roles — ADR-0027 / doc §12) ----
  // Injectors are sources: a universal `All` plus the leaves. Type-based
  // injectors are hidden for single-type kinds (they'd be noise, #91).
  let hasTypeChoice = $derived(entryTypeOptions.length > 1);
  let INJECTORS = $derived<{ kind: GraphNodeKind; label: string }[]>([
    { kind: "all", label: "All" },
    ...(hasTypeChoice
      ? ([
          { kind: "type", label: "Type" },
          { kind: "descendants_of", label: "Type + subtypes" },
        ] as { kind: GraphNodeKind; label: string }[])
      : []),
    { kind: "tagged", label: "Tag" },
    { kind: "field", label: "Field" },
    { kind: "hand_picked", label: "Hand-picked" },
    { kind: "view_ref", label: "Saved view" },
  ]);
  // Filter is the everyday transform; series = AND, parallel = OR by topology.
  const FILTERS: { kind: GraphNodeKind; label: string }[] = [{ kind: "filter", label: "Filter" }];
  // Operations — the explicit set combinators, the power tier.
  const OPERATIONS: { kind: GraphNodeKind; label: string }[] = [
    { kind: "union", label: "Union" },
    { kind: "intersect", label: "Intersect" },
    { kind: "difference", label: "Difference" },
    { kind: "complement", label: "Complement" },
  ];
  // Arrange — per-segment Sort + the color Highlight overlay.
  const ARRANGE: { kind: GraphNodeKind; label: string }[] = [
    { kind: "sorter", label: "Sort" },
    { kind: "highlight", label: "Highlight" },
  ];

  function defaultCfg(k: GraphNodeKind): ViewNodeData {
    if (k === "filter") return { filter_mode: "keep", filter_kind: hasTypeChoice ? "type" : "tagged" };
    if (k === "sorter") return { sort: { by: "title", dir: "asc" } };
    return {};
  }
  function addNode(k: GraphNodeKind): void {
    const id = `a${addCounter++}`;
    const position = { x: 60, y: 60 + (flowNodes.length % 8) * 46 };
    flowNodes = [...flowNodes, toFlowNode(id, k, defaultCfg(k), position)];
  }

  // ---- connection wiring ----
  function isValidConnection(conn: { source?: string | null; target?: string | null }): boolean {
    if (!conn.source || !conn.target || conn.source === conn.target) return false;
    const target = flowNodes.find((n) => n.id === conn.target);
    if (!target || inputArity(target.data.kind) === "none") return false;
    const edges = flowEdges.map((e) => ({ id: e.id, source: e.source, target: e.target, targetHandle: e.targetHandle ?? null }));
    return !wouldCycle(edges, conn.source, conn.target);
  }
  // After a connection auto-adds, trim single-input handles to their newest edge
  // (union/intersect keep all). Newest wins so a re-wire replaces cleanly.
  function normalizeEdges(): void {
    const kept: Edge[] = [];
    const seen = new Set<string>();
    for (let i = flowEdges.length - 1; i >= 0; i--) {
      const e = flowEdges[i];
      const target = flowNodes.find((n) => n.id === e.target);
      // union/intersect and the View (its handles each union) accept many wires;
      // everything else keeps only its newest edge per target handle.
      const many =
        target?.data.kind === "union" || target?.data.kind === "intersect" || target?.data.kind === "output";
      const key = `${e.target}::${e.targetHandle ?? "in"}`;
      if (!many) {
        if (seen.has(key)) continue;
        seen.add(key);
      }
      kept.push(e);
    }
    kept.reverse();
    if (kept.length !== flowEdges.length) flowEdges = kept;
  }

  // ---- persistence (debounced) ----
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let lastSaved = "";
  $effect(() => {
    // Layout is in the snapshot so a position-only drag (which leaves `spec`
    // unchanged) still triggers a persist.
    const snapshot = JSON.stringify({ title, spec, presentation, layout: toLayout() });
    if (hydrating || !loadedViewId) {
      lastSaved = snapshot;
      return;
    }
    if (snapshot === untrack(() => lastSaved)) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveTimer = null;
      void persist(snapshot);
    }, 600);
  });
  async function persist(snapshot: string): Promise<void> {
    if (!loadedViewId) return;
    try {
      const saved = await api.saveView(loadedViewId, {
        title: title || "Untitled view",
        base_revision: revision,
        spec,
        presentation,
        layout: toLayout(),
      });
      revision = saved.revision;
      lastSaved = snapshot;
      onBodyChange?.();
    } catch (e) {
      // Surface via console for step-3 dev; a toast lands with the pane switcher.
      console.error("Failed to save view", e);
    }
  }

  export function setTitleFromPane(next: string): void {
    if (next === title) return;
    title = next;
  }

  function annColor(id: string): string | null {
    return preview.annotations.get(id)?.color ?? null;
  }

  // Preview group collapse (per group key) — reuse the GroupCaret affordance the
  // panes use so the designer preview matches (#84 rollup).
  let collapsedPreview = $state<Record<string, boolean>>({});
  function togglePreviewGroup(key: string): void {
    collapsedPreview = { ...collapsedPreview, [key]: !collapsedPreview[key] };
  }

  // When the anchor kind changes, stale type/field leaves no longer apply — reset
  // to a blank graph (keep only the output). Skipped during hydration.
  let lastKind = $state("");
  $effect(() => {
    const k = kind;
    if (hydrating) {
      lastKind = k;
      return;
    }
    if (lastKind && lastKind !== k) {
      flowNodes = flowNodes.filter((n) => n.data.kind === "output");
      flowEdges = [];
      void loadSavedViews(k, loadedViewId);
    }
    lastKind = k;
  });

  // v1 preview universes are the summary-backed kinds the pane already holds.
  // Scene/research previews arrive with the pane switchers (step 4).
  const KIND_CHOICES = ["lore", "assistant", "prompt"];
</script>

<section class="view-designer" onfocusin={() => onFocus?.()}>
  <div class="designer-toolbar">
    <label class="kind-pick">
      <span>Views over</span>
      <select bind:value={kind}>
        {#each KIND_CHOICES as k (k)}
          <option value={k}>{k}</option>
        {/each}
      </select>
    </label>
    <div class="palette">
      <span class="pal-group">
        {#each INJECTORS as p (p.kind)}
          <button type="button" class="inj" onclick={() => addNode(p.kind)}>{p.label}</button>
        {/each}
      </span>
      <span class="pal-sep"></span>
      <span class="pal-group">
        {#each FILTERS as p (p.kind)}
          <button type="button" class="filter" onclick={() => addNode(p.kind)}>{p.label}</button>
        {/each}
      </span>
      <span class="pal-sep"></span>
      <span class="pal-group">
        {#each OPERATIONS as p (p.kind)}
          <button type="button" class="op" onclick={() => addNode(p.kind)}>{p.label}</button>
        {/each}
      </span>
      <span class="pal-sep"></span>
      <span class="pal-group">
        {#each ARRANGE as p (p.kind)}
          <button type="button" class="ann" onclick={() => addNode(p.kind)}>{p.label}</button>
        {/each}
      </span>
    </div>
  </div>

  <div class="designer-body">
    <div class="canvas">
      <SvelteFlow
        bind:nodes={flowNodes}
        bind:edges={flowEdges}
        {nodeTypes}
        {colorMode}
        {isValidConnection}
        onconnect={normalizeEdges}
        deleteKey={["Backspace", "Delete"]}
        fitView
        minZoom={0.3}
      >
        <Background />
        <Controls />
        <FitView trigger={`${loadedViewId}:${flowNodes.length}`} />
      </SvelteFlow>
      {#if flowNodes.length <= 1}
        <!-- Overlay, NOT a Svelte Flow <Panel>: a Panel captures pointer events
             over the canvas and blocks the handles (no crosshair / no connect). -->
        <div class="empty-hint">Drop an <strong>All</strong>, chain a <strong>Filter</strong> or two, then wire into <strong>View result</strong>.</div>
      {/if}
    </div>

    <aside class="preview">
      <header class="preview-head">
        <span>Preview</span>
        <span class="count">{preview.nodes.length} / {universe.length}</span>
      </header>
      <div class="preview-list">
        {#if universe.length === 0}
          <p class="preview-empty">No <code>{kind}</code> nodes in this project to preview.</p>
        {:else if preview.groups}
          {#each preview.groups as group (group.key)}
            <div class="pgroup">
              <button
                type="button"
                class="pgroup-head"
                style={group.color ? `--tint:${group.color}` : ""}
                aria-expanded={!collapsedPreview[group.key]}
                onclick={() => togglePreviewGroup(group.key)}
              >
                <GroupCaret collapsed={collapsedPreview[group.key]} />
                <span class="pgroup-label">{group.label ?? "Everything else"}</span>
                <span class="count">{group.nodes.length}</span>
              </button>
              {#if !collapsedPreview[group.key]}
                {#each group.nodes as n (n.id)}
                  <div class="prow" style={annColor(n.id) ? `--tint:${annColor(n.id)}` : ""}>{n.title}</div>
                {/each}
              {/if}
            </div>
          {/each}
        {:else}
          {#each preview.nodes as n (n.id)}
            <div class="prow" style={annColor(n.id) ? `--tint:${annColor(n.id)}` : ""}>{n.title}</div>
          {/each}
          {#if preview.nodes.length === 0}
            <p class="preview-empty">No matches — the current expression selects nothing.</p>
          {/if}
        {/if}
      </div>
    </aside>
  </div>
</section>

<style>
  .view-designer {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--panel, #fff);
  }
  .designer-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border, #e2e5ea);
    flex-wrap: wrap;
  }
  .kind-pick {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-3, #6b7280);
  }
  .kind-pick select {
    padding: 3px 6px;
    border: 1px solid var(--border, #e2e5ea);
    border-radius: 6px;
    font-size: 12px;
  }
  .palette {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .pal-group {
    display: inline-flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  .pal-sep {
    width: 1px;
    height: 18px;
    background: var(--border, #e2e5ea);
  }
  .palette button {
    padding: 3px 8px;
    border: 1px solid var(--border-strong, #cbd0d8);
    border-radius: 6px;
    background: var(--panel, #fff);
    font-size: 11.5px;
    cursor: pointer;
  }
  .palette button:hover {
    background: var(--inset, #f2f4f7);
  }
  .palette button.filter {
    border-color: var(--accent, #4361ee);
    background: var(--accent, #4361ee);
    color: #fff;
    font-weight: 600;
  }
  .palette button.op {
    border-color: var(--accent, #4361ee);
    color: var(--accent, #4361ee);
  }
  .palette button.ann {
    border-style: dashed;
  }
  .designer-body {
    display: flex;
    flex: 1;
    min-height: 0;
  }
  .canvas {
    flex: 1;
    min-width: 0;
    min-height: 0;
    position: relative;
    /* Clip the flow so a node can never paint over the toolbar/preview. */
    overflow: hidden;
  }
  /* Svelte Flow needs an explicitly sized parent. */
  .canvas :global(.svelte-flow) {
    height: 100%;
  }
  .empty-hint {
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 4;
    /* Must not intercept pointer events — the handles live under it. */
    pointer-events: none;
    background: var(--inset, #f2f4f7);
    border: 1px dashed var(--border-strong, #cbd0d8);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    color: var(--text-3, #6b7280);
  }
  .preview {
    width: 260px;
    flex-shrink: 0;
    border-left: 1px solid var(--border, #e2e5ea);
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--inset, #fafbfc);
  }
  .preview-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 8px 12px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3, #6b7280);
    border-bottom: 1px solid var(--border, #e2e5ea);
  }
  .count {
    font-variant-numeric: tabular-nums;
    color: var(--text-3, #6b7280);
  }
  .preview-list {
    flex: 1;
    overflow-y: auto;
    padding: 6px;
  }
  .preview-empty {
    padding: 12px;
    font-size: 12px;
    color: var(--text-3, #6b7280);
  }
  .pgroup {
    margin-bottom: 8px;
  }
  .pgroup-head {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
    text-align: left;
    color: var(--text, #1f2430);
    border: none;
    border-left: 3px solid var(--tint, var(--border-strong, #cbd0d8));
    background: var(--panel, #fff);
    border-radius: 4px;
    cursor: pointer;
  }
  .pgroup-label {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pgroup-head:hover {
    background: var(--inset, #f2f4f7);
  }
  .prow {
    padding: 4px 8px 4px 11px;
    font-size: 12.5px;
    border-left: 3px solid var(--tint, transparent);
    border-radius: 3px;
  }
  .prow:hover {
    background: var(--panel, #fff);
  }
</style>
