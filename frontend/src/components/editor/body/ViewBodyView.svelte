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
  import { SvelteFlow, Controls, type ColorMode, type Node, type Edge } from "@xyflow/svelte";
  import { untrack } from "svelte";
  import { themePreference } from "@/lib/utils/theme";
  import ViewFlowNode from "./view/ViewFlowNode.svelte";
  import SelfLoopEdge from "./view/SelfLoopEdge.svelte";
  import ViewportFit from "./view/ViewportFit.svelte";
  import ParamMark from "./view/ParamMark.svelte";
  import ViewGlyph from "./view/ViewGlyph.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import { setDesignerContext, type DesignerContext, type FieldOption, type RosterWarning } from "./view/designerContext";
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { knownTagsStore } from "@/lib/stores/tags";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { evaluateView, nestWarnings, type EvalNode, type EvalBindings } from "@/lib/views/evaluateView";
  import { buildBindings } from "@/lib/views/viewParams";
  import ParamStrip from "./view/ParamStrip.svelte";
  import {
    effectiveFieldLabel,
    effectiveFieldHidden,
    kindRootEntryTypeId,
    kindEntryTypeFqns,
    descendantTypeFqns,
    intersectFieldKeysOverTypes,
  } from "@/lib/utils/schemaTypeHelpers";
  import { pickerMembership } from "@/lib/utils/pickerSources";
  import { structureToEvalNodes } from "@/lib/views/structureNodes";
  import { repairGraphCycles as repairGraphCycles_ } from "@/lib/views/cycleCheck";
  import {
    specToGraph,
    graphToSpec,
    collectParamBindings,
    isEmptyValue,
    inputArity,
    classifyConnection,
    connectionAllowed,
    reachesFieldOf,
    outputPayload,
    valueSlotAccepts,
    inferInputTypes,
    inputKinds,
    tagAppliesToInput,
    anchorSet,
    defaultFilterKind,
    FILTER_VALUE_HANDLE,
    OUTPUT_NODE_ID,
    type GraphNodeKind,
    type ViewGraph,
    type ViewGraphNode,
    type ViewGraphEdge,
    type ViewNodeData,
    type InputTypeSet,
    type TypeResolvers,
  } from "@/lib/views/viewGraph";
  import type {
    AssistantEntrySummary,
    EditableDocument,
    LoreEntrySummary,
    MetadataFieldDefinition,
    PromptEntrySummary,
    ScopedTag,
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
  // Reverse reference index backing the `references` computed field so the
  // designer preview resolves backlink projections (#184 Phase 2).
  let referenceIndex = $derived($referenceIndexStore);
  // Svelte Flow ships light-only chrome; drive its theme from the app's. The
  // preference values ("system"/"light"/"dark") map straight to ColorMode.
  let colorMode = $derived($themePreference as ColorMode);

  // Which designer node is expanded to its full editor (#220, §A). Header-click
  // toggles it; a canvas-background click (onpaneclick) clears it. Ephemeral.
  let expandedId = $state<string | null>(null);
  function toggleExpanded(id: string): void {
    expandedId = expandedId === id ? null : id;
  }

  // Preview aside fold (#220, ADR-0038 §A): default open; collapses to a thin
  // strip to hand the canvas the full width. Ephemeral this pass — persisting it
  // on the view node's `/ui` (ADR-0036) is a small follow-up (the designer has
  // no `/ui` write path today; that's the view panes' CollapseState).
  let previewCollapsed = $state(false);

  // Parameters rail (ADR-0038 §D, #222): the view-level overview of every promoted
  // formal — the rail's ONE job (per-node config edits in place, not here). Each
  // row navigates to + expands its owning node. Collapsible like the preview;
  // ephemeral this pass. Runtime *binding* stays on the render surface (#182/#199).
  let paramsCollapsed = $state(false);
  // A fresh object per navigate request so re-clicking the same row re-centers.
  let focusRequest = $state<{ id: string } | null>(null);
  function focusParamNode(nodeId: string): void {
    expandedId = nodeId;
    flowNodes = flowNodes.map((n) => ({ ...n, selected: n.id === nodeId }));
    focusRequest = { id: nodeId };
  }
  // Display rows for the rail: label, inferred type, default text, bound state,
  // owning node. Derived off the graph (recomputes on any edit — light: no eval).
  type ParamRow = { nodeId: string; name: string; label: string; typeLabel: string; defaultText: string; bound: boolean };
  let paramRows = $derived.by<ParamRow[]>(() =>
    collectParamBindings(toGraph()).map((b) => {
      const cfg = flowNodes.find((n) => n.id === b.nodeId)?.data.cfg ?? {};
      const def = b.param.default;
      const bound = !isEmptyValue(def);
      let typeLabel: string;
      let defaultText: string;
      if (b.slot === "tagged") {
        typeLabel = "tag";
        defaultText = bound ? String(def) : "";
      } else if (b.slot === "type" || b.slot === "descendants_of") {
        typeLabel = "entry type";
        defaultText = bound ? (entryTypeOptions.find((t) => t.fqn === def)?.name ?? String(def)) : "";
      } else {
        // field slot — the field's datatype, and the field name folds into the label.
        const fdef = cfg.field?.key ? schema?.fields?.[cfg.field.key] : null;
        typeLabel = fdef?.type ?? "value";
        defaultText = bound ? (Array.isArray(def) ? def.join(", ") : String(def)) : "";
      }
      return { nodeId: b.nodeId, name: b.param.name, label: b.param.label || b.param.name, typeLabel, defaultText, bound };
    }),
  );

  // The view node's editable state. `title` is fed from the pane header.
  let loadedViewId = $state<string | null>(null);
  let revision = $state("");
  let title = $state("");
  let kind = $state("lore");
  let sort = $state<ViewSort>({ by: "manual" });

  // Svelte Flow graph — the source of truth for the expression, bound to the
  // canvas. Custom nodes all use the single "viewNode" type; data carries the
  // graph kind + its config.
  type FlowData = { kind: GraphNodeKind; cfg: ViewNodeData };
  let flowNodes = $state<Node<FlowData>[]>([]);
  let flowEdges = $state<Edge[]>([]);
  // `${nodeId}:${handleId}` for every wired endpoint — built once per edge change
  // so `handleConnected` / `valueWired` are O(1) lookups rather than a per-handle
  // scan of every edge (§240). Reactive: re-derives when flowEdges changes.
  let connectedHandleKeys = $derived.by(() => {
    const keys = new Set<string>();
    for (const e of flowEdges) {
      if (e.sourceHandle) keys.add(`${e.source}:${e.sourceHandle}`);
      if (e.targetHandle) keys.add(`${e.target}:${e.targetHandle}`);
    }
    return keys;
  });
  // The canvas element, so insertion can invert screen→flow coords by reading the
  // live viewport transform straight off the DOM (§E) — `bind:viewport` only
  // emits on a viewport CHANGE, so it stays undefined until the first pan/zoom.
  let canvasEl = $state<HTMLDivElement | undefined>(undefined);
  const nodeTypes = { viewNode: ViewFlowNode };
  const edgeTypes = { selfloop: SelfLoopEdge };

  let addCounter = 0;
  let hydrating = false;

  // ---- hydrate from the opened view node ----
  $effect(() => {
    const node = scene as ViewNode | null;
    const id = node?.id ?? null;
    if (!node || !("spec" in node)) return;
    // Wait for the metadata schema before hydrating: `hydrateGraph`→`specToGraph`
    // resolves the roster / kind root against it, so a null schema hydrates a
    // roster-based view to an empty graph that WON'T re-hydrate (this effect is
    // id-guarded below). Reading `schema` (a `$derived` of the store) re-runs this
    // effect when it loads; the id-guard then still fires once per opened view.
    if (schema == null) return;
    if (id === untrack(() => loadedViewId)) return;
    hydrating = true;
    loadedViewId = id;
    expandedId = null; // a freshly-opened view starts fully collapsed
    revision = node.revision ?? "";
    title = node.title ?? "";
    kind = node.spec?.kind ?? "lore";
    sort = node.spec?.sort ?? { by: "manual" };
    // Prefer the persisted designer layout (exact positions the author left);
    // fall back to laying out the semantic expr for designer-less / legacy views.
    // Handle ids are explicit so Svelte Flow renders these edges once the new
    // nodes' handle bounds are measured (its layout pass is a derived that
    // recomputes after measurement — no manual defer needed).
    const graph = repairGraphCycles(hydrateGraph(node));
    flowNodes = graph.nodes;
    flowEdges = graph.edges;
    // Seed the add-node counter past any `a<N>` id already in the loaded graph.
    // Persisted layouts store the exact ids addNode minted in a prior session, so
    // a fresh `addCounter = 0` would re-emit `a0` and collide — Svelte Flow keys
    // by id, so the "new" node lands on an existing one instead of appending.
    seedAddCounter(graph.nodes);
    // Let the derived spec settle before re-enabling persistence.
    queueMicrotask(() => (hydrating = false));
  });

  function toFlowNode(id: string, k: GraphNodeKind, cfg: ViewNodeData, position: { x: number; y: number }): Node<FlowData> {
    return { id, type: "viewNode", position, data: { kind: k, cfg }, deletable: k !== "output" };
  }

  // The two wire types (ADR-0031 §D): a node-set pipe (solid, the default) vs a
  // value-set pipe (a scalar `field_of` — dashed, tinted the value colour). The
  // class is derived from the source's `outputPayload`, so it survives a layout
  // round-trip (never persisted) — recomputed on hydrate, connect, and whenever a
  // field_of's projected field changes its payload.
  function edgeClass(sourceId: string, nodes: Node<FlowData>[]): string | undefined {
    const s = nodes.find((n) => n.id === sourceId);
    if (!s) return undefined;
    const gn: ViewGraphNode = { id: s.id, kind: s.data.kind, position: s.position, data: s.data.cfg ?? {} };
    const fieldType = (key: string) => schema?.fields?.[key]?.type ?? null;
    return outputPayload(gn, fieldType) === "value-set" ? "value-wire" : undefined;
  }
  function tagEdge(e: Edge, nodes: Node<FlowData>[]): Edge {
    const cls = edgeClass(e.source, nodes);
    return (e.class ?? undefined) === cls ? e : { ...e, class: cls };
  }

  // Build the canvas graph for a view: from its persisted designer `layout`
  // (author's exact positions + wiring) when present, else auto-laid-out from
  // the semantic `expr` (designer-less / legacy / backend-authored views).
  function hydrateGraph(node: ViewNode): { nodes: Node<FlowData>[]; edges: Edge[] } {
    const layout = node.layout;
    if (layout && layout.nodes.length > 0) {
      const rawNodes = layout.nodes.map((n) =>
        toFlowNode(n.id, n.kind as GraphNodeKind, (n.cfg ?? {}) as ViewNodeData, n.position),
      );
      const rawEdges = layout.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.source_handle ?? undefined,
        targetHandle: e.target_handle ?? undefined,
        type: e.source === e.target ? "selfloop" : undefined,
      }));
      // A persisted layout is authored in the first-class idiom (#271 retired the
      // bare-predicate-leaf → `All → Filter` canonicalization), so it hydrates as-is.
      return { nodes: rawNodes, edges: rawEdges.map((e) => ({ ...e, class: edgeClass(e.source, rawNodes) })) };
    }
    const g = specToGraph(node.spec, schema);
    const nodes = g.nodes.map((n) => toFlowNode(n.id, n.kind, n.data, n.position));
    return {
      nodes,
      edges: g.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? undefined,
        targetHandle: e.targetHandle ?? undefined,
        type: e.source === e.target ? "selfloop" : undefined,
        class: edgeClass(e.source, nodes),
      })),
    };
  }

  // Load-time DAG-invariant repair (#275, ADR-0028 §D): silently drop any illegal
  // back-edge in the hydrated graph (a hand-edited file / a previously-buggy
  // designer's output) so the view still opens; the repair persists on the next
  // debounced save. The invariant + the one legal exception live in cycleCheck.
  function repairGraphCycles(graph: { nodes: Node<FlowData>[]; edges: Edge[] }): {
    nodes: Node<FlowData>[];
    edges: Edge[];
  } {
    const kindById = new Map(graph.nodes.map((n) => [n.id, n.data.kind]));
    const { edges, dropped } = repairGraphCycles_(kindById, graph.edges);
    if (dropped.length > 0 && import.meta.env.DEV) {
      console.warn(`[views] load-time repair: dropped ${dropped.length} cyclic edge(s)`, dropped);
    }
    return { nodes: graph.nodes, edges };
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

  // ---- graph → spec ----
  function toGraph(): ViewGraph {
    return {
      nodes: flowNodes.map((n) => ({ id: n.id, kind: n.data.kind, position: n.position, data: n.data.cfg ?? {} })),
      // sourceHandle is load-bearing for the Nest orphans output (ADR-0028 Amdt 1,
      // #260): graphToSpec folds an edge leaving the `orphans` handle into
      // `nest.orphans`. It was dropped before that handle existed.
      edges: flowEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
      })),
    };
  }
  // Memoize the lowered spec by structural equality. Dragging a node mutates
  // flowNodes' positions every animation frame, but positions only feed n-ary
  // child ORDERING in graphToSpec, which rarely changes mid-drag. Returning the
  // SAME spec reference when the lowering is unchanged stops `preview` — a
  // $derived that re-evaluates the whole universe — from recomputing every drag
  // frame (#96). The autosave effect still tracks positions via toLayout().
  let specMemo: { key: string; spec: ViewSpec } | null = null;
  let spec = $derived.by<ViewSpec>(() => {
    const next = graphToSpec(toGraph(), { kind, sort, schema });
    const key = JSON.stringify(next);
    if (specMemo && specMemo.key === key) return specMemo.spec;
    specMemo = { key, spec: next };
    return next;
  });

  // ---- preview universe for the anchor kind ----
  let universe = $derived<EvalNode[]>(universeFor(kind));
  function universeFor(k: string): EvalNode[] {
    if (k === "lore") return loreEntries;
    if (k === "assistant") return assistantEntries;
    if (k === "prompt") return promptEntries;
    if (k === "scene") return structureToEvalNodes(structure);
    return [];
  }
  // The preview MUST evaluate what the pane will, or the designer can't verify the
  // view's logic (Anton). So it binds the view's parameters exactly as the pane's
  // ViewNodeList does — `buildBindings` seeds each formal from its authored default
  // and applies the designer's own overrides (the editable ParamStrip in the rail).
  // Without this the preview ran every parameter UNBOUND, diverging from the pane.
  let paramOverrides = $state<Record<string, unknown>>({});
  const previewBindings = $derived.by((): EvalBindings => buildBindings(spec.params, paramOverrides));
  let preview = $derived(
    evaluateView(spec, universe, {
      schema,
      referenceIndex,
      bindings: previewBindings,
    }),
  );
  // Nest diagnostics surfaced as warnings so a truncated/lossy tree is never
  // silent (ADR-0028 §D, #110).
  let warnings = $derived(nestWarnings(preview.diagnostics));

  // ---- schema-derived leaf-config options for the current kind ----
  let entryTypeOptions = $derived(
    Object.entries(schema?.entry_types ?? {})
      .filter(([, def]) => def.kind === kind && !def.abstract)
      .map(([fqn, def]) => ({ fqn, name: def.name })),
  );
  // The intrinsic identity fields (id/title/entry_type, #116) are now regular
  // schema fields injected into every entry_type, so title/entry_type surface
  // here naturally — pinned first (intrinsic before metadata). `hidden` fields
  // (id by default) are skipped; the evaluator reads intrinsic keys off the
  // node property (see fieldValue).
  // Shared roster builder: field keys → sorted FieldOptions, resolving per-type
  // label/hidden against `anchor` — the kind ROOT for a single kind (ADR-0029 §F:
  // the built-in lore `title → "Name"` relabel sits on `lore:base` and reaches the
  // picker; a leaf-only override deliberately does not), or the bare def (null) for
  // a cross-kind set with no single root. Intrinsics (id/title/entry_type, #116)
  // are regular injected fields, pinned first; `hidden` ones (id) are skipped.
  function fieldOptionsFromKeys(keys: Iterable<string>, anchor: string | null): FieldOption[] {
    const out: FieldOption[] = [];
    for (const k of keys) {
      const def = schema?.fields?.[k];
      if (!def || effectiveFieldHidden(schema, anchor, k)) continue;
      out.push({ key: k, name: effectiveFieldLabel(schema, anchor, k), def });
    }
    out.sort((a, b) => {
      const ai = a.def.category === "intrinsic";
      const bi = b.def.category === "intrinsic";
      if (ai !== bi) return ai ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    return out;
  }
  // Structural containment ref (ADR-0029 §D `computed` category / #217): scenes
  // and research notes carry a `parent` metadata ref stamped from the structure
  // tree (`structureNodes.ts`), which drives `defaultView()`'s containment Nest.
  // It's not a schema-declared field, so it's absent from the entry_type rosters
  // — leaving every field picker (filter predicate, Nest link, field_of, group_by)
  // unable to show, select, or RESTORE it (#251). Inject it as a first-class
  // computed reference field so all those pickers offer it uniformly. `entity_ref`
  // + non-intrinsic category = joinable AND groupable, matching how the evaluator
  // follows it (`match.field: parent`, by ref). `children` is deferred to #217: no
  // node stamps it, so the evaluator has no inverse index to resolve it yet.
  const STRUCTURAL_KINDS = new Set(["scene", "research"]);
  // The structural `parent` ref as a computed reference field, scoped to kind `k`
  // so its value widget (op overlap/disjoint → ReferencePicker) offers that kind's
  // nodes — without a `picker_config` the picker falls back to the `lore` roster.
  function parentFieldDef(k: string): MetadataFieldDefinition {
    return { name: "Parent", type: "entity_ref", options: [], category: "computed", picker_config: { sources: [{ kind: k }] } };
  }
  // The structural field options for a set of kinds — `parent` when any is a
  // structural (tree) kind, else none. Prepended to a roster, not merged into the
  // schema-key set, since it has no entry_type membership to intersect over. A
  // user-declared metadata field literally keyed `parent` (rare) takes precedence:
  // the real field is already in the roster, so skip the synthetic to avoid a
  // duplicate option (`fieldByKey` likewise resolves the schema field first).
  function structuralFieldOptions(kinds: Iterable<string>): FieldOption[] {
    if (schema?.fields?.parent) return [];
    for (const k of kinds) {
      if (STRUCTURAL_KINDS.has(k)) return [{ key: "parent", name: "Parent", def: parentFieldDef(k) }];
    }
    return [];
  }
  // The anchor-kind roster (union of the kind's fields over its entry_types) — the
  // fallback when a node's input type is indeterminate. Per-node rosters come from
  // `fieldsForNode` via §F inference below.
  function buildFieldOptions(forKind: string): FieldOption[] {
    const keys = new Set<string>();
    for (const [, def] of Object.entries(schema?.entry_types ?? {})) {
      if (def.kind !== forKind) continue;
      for (const fk of def.fields ?? []) keys.add(fk);
    }
    return [...structuralFieldOptions([forKind]), ...fieldOptionsFromKeys(keys, kindRootEntryTypeId(schema, forKind))];
  }
  let fieldOptions = $derived(buildFieldOptions(kind));
  // Authoring-time TYPE inference (ADR-0031 §F): the entry_type-set of a node's
  // INPUT set, driving which field roster AND tag roster its picker offers.
  const fieldType = (key: string) => schema?.fields?.[key]?.type ?? null;
  const typeResolvers: TypeResolvers = {
    fieldType,
    // A ref field's target as a type-set: kind → its entry_type FQNs (empty →
    // whole kind, no entry_type constraint). Multi-kind refs are kept, not nulled
    // — the roster intersects across them (§14.3).
    refTargetTypes: (fieldKey) => {
      const def = schema?.fields?.[fieldKey];
      if (!def) return null;
      const { kinds, entryTypes } = pickerMembership(def.picker_config);
      if (kinds.length === 0) return null;
      return new Map(kinds.map((k) => [k, entryTypes[k]?.length ? new Set(entryTypes[k]) : null]));
    },
    descendantsOf: (fqn) => descendantTypeFqns(schema, fqn),
    kindOfType: (fqn) => schema?.entry_types?.[fqn]?.kind ?? fqn.split(":")[0] ?? null,
  };
  // Rebuilt once per graph mutation (a $derived), not per picker call — both
  // `fieldsForNode` and `knownTagsFor` run per node per render, so a per-call
  // rebuild would be O(N²) over the node count.
  let inferenceGraph = $derived.by((): { byId: Map<string, ViewGraphNode>; edges: ViewGraphEdge[] } => ({
    byId: new Map(
      flowNodes.map((n) => [n.id, { id: n.id, kind: n.data.kind, position: n.position, data: n.data.cfg ?? {} }]),
    ),
    edges: flowEdges.map((e) => ({ id: e.id, source: e.source, target: e.target, targetHandle: e.targetHandle ?? null })),
  }));
  function inputTypesForNode(nodeId: string): InputTypeSet | null {
    return inferInputTypes(inferenceGraph.byId, inferenceGraph.edges, nodeId, kind, typeResolvers);
  }
  // Expand an inferred input type-set to the concrete entry_type FQNs it can hold
  // (a `null` per-kind constraint → every concrete type of that kind).
  function concreteTypesOf(ts: InputTypeSet): string[] {
    const out: string[] = [];
    for (const [k, set] of ts) out.push(...(set ? [...set] : kindEntryTypeFqns(schema, k)));
    return out;
  }
  function fieldsForNode(nodeId: string): FieldOption[] {
    const ts = inputTypesForNode(nodeId);
    if (!ts) return fieldOptions; // indeterminate → anchor roster
    const fqns = concreteTypesOf(ts);
    // Determinate but provably empty (e.g. an intersect of disjoint types) — the
    // set can hold no members, so only the always-present intrinsics apply.
    if (fqns.length === 0) return fieldOptions.filter((o) => o.def.category === "intrinsic");
    // §F: the fields present on EVERY member — a group-aware set-intersection over
    // the input's concrete types (vertical inheritance AND shared field-groups). A
    // cross-kind set has no single root → resolve labels against the bare def. The
    // structural `parent` (prepended) isn't an entry_type member, so it survives
    // the intersection only by being added here — offered whenever a structural
    // kind is in play (the indeterminate branch above inherits it via `fieldOptions`).
    const anchor = ts.size === 1 ? kindRootEntryTypeId(schema, [...ts.keys()][0]) : null;
    return [...structuralFieldOptions(ts.keys()), ...fieldOptionsFromKeys(intersectFieldKeysOverTypes(schema, fqns), anchor)];
  }
  // The authoring warning ADR-0031 §F asks for (Slice B, #215): when a picker
  // node's inferred INPUT set is cross-kind, its roster is a degraded intersection,
  // not the precise single-kind roster. Cross-kind ⇔ the type-set spans a number of
  // kinds OTHER than exactly one:
  //  - size > 1 — a genuine multi-kind set (union of kinds, cross-kind ref, Nest);
  //  - size 0 (a determinate, NON-null empty Map) — a cross-kind INTERSECT that
  //    collapsed to nothing (`combineTypeSets` drops every kind when the branches
  //    share none, e.g. `scenes ∩ characters`), the thinnest roster of all and
  //    exactly the "nothing in common → down to intrinsics" case §F names.
  // Silent (null) otherwise: `ts === null` (indeterminate → anchor fallback), and
  // size 1 — a single kind, INCLUDING a same-kind empty intersect (`{scene:∅}`),
  // which is a distinct impossible-filter diagnostic out of §F's cross-kind scope.
  // `thin` reuses `fieldsForNode` (the roster the picker actually shows), so for a
  // cross-kind node the note always agrees with the dropdown.
  function rosterWarningFor(nodeId: string): RosterWarning | null {
    const ts = inputTypesForNode(nodeId);
    if (ts === null || ts.size === 1) return null;
    const kinds = inputKinds(ts).sort();
    const thin = !fieldsForNode(nodeId).some((o) => o.def.category !== "intrinsic");
    return { kinds, thin };
  }
  // Per-node tag roster (#243 → #215): tags whose scope matches the node's inferred
  // INPUT type-set — kind AND (when the tag narrows to entry_types) type, the
  // "input pipe". Re-emitted unscoped so the TagPicker shows the whole matched set;
  // an indeterminate input falls back to the anchor kind.
  function knownTagsFor(nodeId: string): ScopedTag[] {
    const ts: InputTypeSet = inputTypesForNode(nodeId) ?? anchorSet(kind);
    return $knownTagsStore
      .filter((t) => tagAppliesToInput(t.scope, ts, typeResolvers.descendantsOf))
      .map((t) => ({ ...t, scope: { sources: [] } }));
  }
  // ---- designer context for the custom nodes ----
  setDesignerContext(
    (): DesignerContext => ({
      updateNodeData,
      removeNode,
      expandedId,
      toggleExpanded,
      kind,
      entryTypes: entryTypeOptions,
      fields: fieldOptions,
      fieldsFor: fieldsForNode,
      rosterWarningFor,
      fieldByKey: (key: string) =>
        schema?.fields?.[key] ?? (key === "parent" && STRUCTURAL_KINDS.has(kind) ? parentFieldDef(kind) : null),
      valueWired: (nodeId: string) => connectedHandleKeys.has(`${nodeId}:${FILTER_VALUE_HANDLE}`),
      handleConnected: (nodeId: string, handleId: string) => connectedHandleKeys.has(`${nodeId}:${handleId}`),
      knownTagsFor,
      loreEntries,
      promptEntries,
      assistantEntries,
      structure,
      researchStructure,
    }),
  );

  function updateNodeData(id: string, patch: Partial<ViewNodeData>): void {
    flowNodes = flowNodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, cfg: { ...n.data.cfg, ...patch } } } : n));
    // A config edit can invalidate the edges this node touches, in both
    // directions: a payload FLIP (node-set ⇄ value-set — a field_of switched
    // between a scalar and a reference field) breaks its OUTGOING edges, and a
    // value-slot field-key change (scalar ⇄ reference) breaks an INCOMING
    // value-operand edge. Re-run the exact gate used on connect over every
    // incident edge and drop those that no longer pass, so the graph never holds
    // a wire the author couldn't have drawn (which would otherwise lower to a
    // silently type-mismatched spec).
    const stale = new Set(
      flowEdges
        .filter(
          (e) =>
            (e.source === id || e.target === id) &&
            !isValidConnection({ source: e.source, target: e.target, targetHandle: e.targetHandle ?? null }),
        )
        .map((e) => e.id),
    );
    if (stale.size) flowEdges = flowEdges.filter((e) => !stale.has(e.id));
    // Re-tag the remaining edges: a field_of payload change recolours its wire.
    // Only reassigns when a class actually changed (no churn on edits that don't
    // affect payload, e.g. typing a filter value).
    const retagged = flowEdges.map((e) => tagEdge(e, flowNodes));
    if (retagged.some((e, i) => e !== flowEdges[i])) flowEdges = retagged;
  }
  function removeNode(id: string): void {
    if (id === OUTPUT_NODE_ID) return;
    if (expandedId === id) expandedId = null;
    flowNodes = flowNodes.filter((n) => n.id !== id);
    flowEdges = flowEdges.filter((e) => e.source !== id && e.target !== id);
  }

  // ---- palette (sources vs operations — ADR-0038 §B) ----
  // The algebra has two roles: a SOURCE injects a node set, an OPERATION
  // transforms one. The bare predicate leaves (`type / descendants_of / tagged /
  // field`) are retired from the palette — `All → Filter` composes the identical
  // lowering (`commonLeafExpr`) through one UI path, and post-ADR-0036 `All` is a
  // real kind universe, so nothing is lost. `specToGraph` canonicalizes any
  // surviving bare leaf on open, so a reopened or duplicated view never presents
  // vocabulary the palette can't rebuild. Each chip carries the kind's ViewGlyph
  // (the same mark as the node header, §240), so it needs no per-item colour cue.
  let hasTypeChoice = $derived(entryTypeOptions.length > 1);
  type PalItem = { kind: GraphNodeKind; label: string };
  const PALETTE: { label: string; items: PalItem[] }[] = [
    {
      label: "Sources",
      items: [
        { kind: "all", label: "All" },
        { kind: "hand_picked", label: "Hand-picked" },
        // `This entry` ($self) seeds a projection from the pane's anchor.
        { kind: "self", label: "This entry" },
      ],
    },
    {
      label: "Operations",
      items: [
        { kind: "filter", label: "Filter" },
        { kind: "field_of", label: "Field of" },
        { kind: "union", label: "Union" },
        { kind: "intersect", label: "Intersect" },
        { kind: "difference", label: "Difference" },
        { kind: "complement", label: "Complement" },
        { kind: "nest", label: "Nest" },
        { kind: "sorter", label: "Sort" },
        { kind: "highlight", label: "Highlight" },
      ],
    },
  ];

  function defaultCfg(k: GraphNodeKind): ViewNodeData {
    if (k === "filter") return { filter_mode: "keep", filter_kind: defaultFilterKind(hasTypeChoice) };
    if (k === "sorter") return { sort: { by: "field", field_key: "title", dir: "asc" } };
    if (k === "nest") return { match: { field: "", direction: "child_to_parent", by: "ref" } };
    return {};
  }
  function addNode(k: GraphNodeKind, position?: { x: number; y: number }): void {
    const id = `a${addCounter++}`;
    flowNodes = [...flowNodes, toFlowNode(id, k, defaultCfg(k), position ?? centrePos())];
  }
  // ---- insertion placement (ADR-0038 §E) ----
  // The equivalent of SvelteFlow's `screenToFlowPosition`, hand-rolled (not the
  // real call — the drop target is the wrapper div, outside the flow provider
  // context `useSvelteFlow()` needs): invert the live viewport transform (read off
  // the DOM) against the canvas rect. Drop lands under the pointer; click lands at
  // the viewport centre (killing the old top-left staircase).
  const DND_MIME = "application/x-view-node-kind";
  function readViewport(): { x: number; y: number; zoom: number } | null {
    const t = canvasEl?.querySelector<HTMLElement>(".svelte-flow__viewport")?.style.transform;
    const m = t ? /translate\(\s*(-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(\s*([\d.]+)\s*\)/.exec(t) : null;
    return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]), zoom: parseFloat(m[3]) } : null;
  }
  function staircaseFallback(): { x: number; y: number } {
    return { x: 60, y: 60 + (flowNodes.length % 8) * 46 };
  }
  function toFlowPos(clientX: number, clientY: number): { x: number; y: number } {
    const rect = canvasEl?.getBoundingClientRect();
    const vp = readViewport();
    if (!rect || !vp) return staircaseFallback();
    return { x: (clientX - rect.left - vp.x) / vp.zoom, y: (clientY - rect.top - vp.y) / vp.zoom };
  }
  function centrePos(): { x: number; y: number } {
    const rect = canvasEl?.getBoundingClientRect();
    const vp = readViewport();
    if (!rect || !vp) return staircaseFallback();
    // Nudge by roughly half a compact node so it reads as centred, not corner-hung.
    return { x: (rect.width / 2 - vp.x) / vp.zoom - 55, y: (rect.height / 2 - vp.y) / vp.zoom - 20 };
  }
  function onPaletteDragStart(e: DragEvent, kind: GraphNodeKind): void {
    if (!e.dataTransfer) return;
    e.dataTransfer.setData(DND_MIME, kind);
    e.dataTransfer.effectAllowed = "copy";
  }
  function onCanvasDragOver(e: DragEvent): void {
    // getData is unreadable during dragover, but the MIME type is visible — gate
    // on it so unrelated drags don't paint a drop cursor over the canvas.
    if (!e.dataTransfer?.types.includes(DND_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }
  function onCanvasDrop(e: DragEvent): void {
    const kind = e.dataTransfer?.getData(DND_MIME);
    if (!kind) return;
    e.preventDefault();
    addNode(kind as GraphNodeKind, toFlowPos(e.clientX, e.clientY));
  }
  // Advance addCounter past the highest `a<N>` id present in `nodes`, so a
  // reopened graph never re-mints an id that's already on the canvas.
  function seedAddCounter(nodes: Node<FlowData>[]): void {
    let max = -1;
    for (const n of nodes) {
      const m = /^a(\d+)$/.exec(n.id);
      if (m) max = Math.max(max, Number(m[1]));
    }
    addCounter = max + 1;
  }

  // ---- connection wiring ----
  // Cycles are no longer a blanket block (ADR-0028 §D): a self-loop into a
  // Nest's `parents` handle is legal recursion. Route every would-be edge
  // through the classifier and permit only clean edges + supported recursion.
  function isValidConnection(conn: {
    source?: string | null;
    target?: string | null;
    targetHandle?: string | null;
    sourceHandle?: string | null;
  }): boolean {
    if (!conn.source || !conn.target) return false;
    const target = flowNodes.find((n) => n.id === conn.target);
    if (!target) return false;
    const byId = new Map<string, ViewGraphNode>(
      flowNodes.map((n) => [n.id, { id: n.id, kind: n.data.kind, position: n.position, data: n.data.cfg ?? {} }]),
    );
    const edges = flowEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      targetHandle: e.targetHandle ?? null,
    }));
    const fieldType = (key: string) => schema?.fields?.[key]?.type ?? null;
    const srcNode = byId.get(conn.source);
    const tgtNode = byId.get(conn.target);
    // The value slot (#196, ADR-0031 §E): a wired operand into a field/Filter's
    // `value` handle. Allowed only when the authored field's payload matches the
    // source's (node-set for entity_ref, value-set for scalar). Bypasses the
    // arity check — a `field` leaf has no set input but does have a value slot.
    if (conn.targetHandle === FILTER_VALUE_HANDLE) {
      if (tgtNode?.kind !== "field" && tgtNode?.kind !== "filter") return false;
      if (!valueSlotAccepts(srcNode, tgtNode.data.field, fieldType)) return false;
      return connectionAllowed(classifyConnection(byId, edges, conn.source, conn.target, conn.targetHandle ?? null, conn.sourceHandle ?? null));
    }
    if (inputArity(target.data.kind) === "none") return false;
    // A value-set source (a scalar `field_of`) may feed ONLY a value slot, never
    // a node-set input — the two-payload accept-matrix (ADR-0031 §E).
    if (outputPayload(srcNode, fieldType) === "value-set") return false;
    // Single-hop cut (#184, §14.5): a field_of's `of` must not resolve from
    // another field_of (multi-hop per-node type inference is deferred).
    if (target.data.kind === "field_of" && reachesFieldOf(byId, edges, conn.source)) return false;
    // NB: `All → field_of` is now permitted (was blocked by #203). Post ADR-0036
    // the whole-kind roster has an explicit expr, so `field_of(All, Type)` lowers
    // to a concrete projection (every entry_type in use) rather than a silent
    // EMPTY — see `fieldOfBuilt`.
    return connectionAllowed(classifyConnection(byId, edges, conn.source, conn.target, conn.targetHandle ?? null, conn.sourceHandle ?? null));
  }
  // After a connection auto-adds, trim single-input handles to their newest edge
  // (union/intersect keep all). Newest wins so a re-wire replaces cleanly.
  function normalizeEdges(): void {
    const kept: Edge[] = [];
    const seen = new Set<string>();
    let changed = false;
    for (let i = flowEdges.length - 1; i >= 0; i--) {
      const e = flowEdges[i];
      const target = flowNodes.find((n) => n.id === e.target);
      // union/intersect and the View (its handles each union) accept many wires;
      // Nest too — its `parents` handle takes both the roots seed AND the
      // recursion self-loop, and each handle unions its sources (ADR-0028).
      // Everything else keeps only its newest edge per target handle.
      const many =
        target?.data.kind === "union" ||
        target?.data.kind === "intersect" ||
        target?.data.kind === "output" ||
        target?.data.kind === "nest";
      const key = `${e.target}::${e.targetHandle ?? "in"}`;
      if (!many) {
        if (seen.has(key)) {
          changed = true;
          continue;
        }
        seen.add(key);
      }
      // A recursion self-loop renders with the custom edge that routes around
      // the node instead of cutting back behind it. Tag every kept edge with its
      // wire-type class (node-set vs value-set) so a freshly-wired pipe paints.
      if (e.source === e.target && e.type !== "selfloop") {
        kept.push(tagEdge({ ...e, type: "selfloop" }, flowNodes));
        changed = true;
      } else {
        const tagged = tagEdge(e, flowNodes);
        if (tagged !== e) changed = true;
        kept.push(tagged);
      }
    }
    kept.reverse();
    if (changed || kept.length !== flowEdges.length) flowEdges = kept;
  }

  // ---- persistence (debounced) ----
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let lastSaved = "";
  $effect(() => {
    // Layout is in the snapshot so a position-only drag (which leaves `spec`
    // unchanged) still triggers a persist.
    const snapshot = JSON.stringify({ title, spec, layout: toLayout() });
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
        layout: toLayout(),
      });
      revision = saved.revision;
      lastSaved = snapshot;
      onBodyChange?.();
      // Refresh the shared saved-view roster so panes consuming this view
      // re-evaluate. Without this, `paneViews.specs` holds the pre-edit spec and
      // consumers stay stale until something else reloads (e.g. opening the
      // ViewSwitcher). Autosave fires before close, so this also covers the
      // "window updates when the editor closes" case.
      void paneViews.reload();
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

  // The preview renders through ViewNodeList (the same wrapper the panes use), so
  // nested `nest` trees (depth > 1) show correctly and the preview is WYSIWYG
  // (#84 rollup; ADR-0028). Collapse is ephemeral, owned by ViewNodeList.

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
    }
    lastKind = k;
  });

</script>

<section class="view-designer" onfocusin={() => onFocus?.()}>
  <div class="designer-toolbar">
    <!--
      The anchor kind is fixed by the pane the view was opened from (Lore / Draft
      / Assistants): every entry point into the designer is a pane ViewSwitcher,
      and re-anchoring an existing graph is destructive (types/fields don't carry
      across kinds). So it reads out static rather than as a footgun <select>
      (#92). A future context-free views surface (#90) can reintroduce a picker
      for the "new blank view, choose its kind" case.
    -->
    <span class="kind-pick" title={`This view is anchored to “${kind}” by the pane it was opened from`}>
      <span>Views over</span>
      <strong class="kind-fixed">{kind}</strong>
    </span>
    <!--
      Sources vs operations (ADR-0038 §B, §240 Editorial-Card pass). A tray you
      pick from, not a toolbar: each item is a glyph-chip on a liftable surface —
      the kind glyph (same mark as the node header, so palette ↔ canvas read as
      one system) + label; hover lifts it and reveals the drag mark. Each chip
      both clicks-to-insert (viewport centre) and drags-to-place (drop point, §E).
    -->
    <div class="palette">
      {#each PALETTE as g (g.label)}
        <div class="pal-group">
          <span class="pal-label">{g.label}</span>
          <div class="pal-chips">
            {#each g.items as p (p.kind)}
              <button
                type="button"
                class="chip"
                draggable="true"
                ondragstart={(e) => onPaletteDragStart(e, p.kind)}
                onclick={() => addNode(p.kind)}
                title={`Click to add, or drag onto the canvas — ${p.label}`}
              >
                <span class="chip-g"><ViewGlyph kind={p.kind} uid={`pal-${p.kind}`} size={16} /></span>
                <span class="chip-label">{p.label}</span>
                <span class="chip-drag" aria-hidden="true">⋮⋮</span>
              </button>
            {/each}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <!-- Shared collapse toggle for the rail-like panes (§240): the same Tabler
       sidebar icon as the editor's details rail. `side` selects the left
       (Parameters) or right (Preview) variant. -->
  {#snippet railToggle(collapsed: boolean, side: "left" | "right", label: string, onToggle: () => void)}
    <button
      type="button"
      class="rail-toggle"
      title={collapsed ? `Expand ${label}` : `Collapse ${label}`}
      aria-label={collapsed ? `Expand ${label}` : `Collapse ${label}`}
      aria-expanded={!collapsed}
      onclick={onToggle}
    ><i class="ti ti-layout-sidebar-{side}-{collapsed ? 'expand' : 'collapse'}" aria-hidden="true"></i></button>
  {/snippet}

  <div class="designer-body">
    <!-- Parameters rail (ADR-0038 §D): the view-level overview of every promoted
         formal. Per-node config edits IN PLACE (§A) — never here; the rail only
         lists declarations and navigates to their nodes. Empty/collapsed when the
         view exposes none — never a config dumping ground. -->
    <aside class="params-rail" class:collapsed={paramsCollapsed}>
      <header class="params-head">
        {@render railToggle(paramsCollapsed, "left", "parameters", () => (paramsCollapsed = !paramsCollapsed))}
        {#if !paramsCollapsed}
          <span class="params-title">Parameters</span>
          {#if paramRows.length > 0}<span class="count">{paramRows.length}</span>{/if}
        {/if}
      </header>
      {#if !paramsCollapsed}
        {#if paramRows.length === 0}
          <p class="params-empty">No parameters. Promote a slot's value (Type, Tag, or a field) to expose one.</p>
        {:else}
          <ul class="params-list">
            {#each paramRows as p (p.name)}
              <li>
                <button type="button" class="param-row" class:unbound={!p.bound} onclick={() => focusParamNode(p.nodeId)} title="Go to this parameter's node">
                  <span class="param-mark"><ParamMark bound={p.bound} /></span>
                  <span class="param-label">{p.label}</span>
                  <span class="param-type">{p.typeLabel}</span>
                  <span class="param-default">{p.bound ? p.defaultText : "no default"}</span>
                </button>
              </li>
            {/each}
          </ul>
          <!-- Editable controls (ADR-0032 §D): vary a value and the preview
               re-evaluates live, so the designer verifies the logic exactly as the
               pane will render it — the SAME `ParamStrip` the pane's ViewNodeList
               now renders (#275), so preview and pane share one implementation. -->
          <ParamStrip {spec} {schema} bind:overrides={paramOverrides} />
        {/if}
      {/if}
    </aside>

    <!-- Drop target for palette drags (§E). The wrapper (not <SvelteFlow>, which
         doesn't type DOM drag props) carries the handlers; role=application so the
         static-element-interaction a11y rule is satisfied for a canvas surface. -->
    <div
      class="canvas"
      bind:this={canvasEl}
      role="application"
      ondragover={onCanvasDragOver}
      ondrop={onCanvasDrop}
    >
      <SvelteFlow
        bind:nodes={flowNodes}
        bind:edges={flowEdges}
        {nodeTypes}
        {edgeTypes}
        {colorMode}
        {isValidConnection}
        onconnect={normalizeEdges}
        onpaneclick={() => (expandedId = null)}
        deleteKey={["Backspace", "Delete"]}
        fitView
        minZoom={0.3}
      >
        <!-- §G: no dotted <Background/> — the canvas is a flat --board surface
             (§1.3: a writing desk, not a whiteboard / graph paper). -->
        <Controls />
        <!-- Reframe on view LOAD only (the opened id), NOT on node count: keying
             on flowNodes.length re-fit the viewport on every drop/delete, shifting
             the origin under the author (§E insertion already places nodes in
             view — pointer for drop, viewport centre for click). -->
        <ViewportFit trigger={loadedViewId} options={{ padding: 0.2, maxZoom: 1 }} />
        <!-- §D: the Parameters rail centers the viewport on ONE formal's node. -->
        <ViewportFit
          trigger={focusRequest}
          options={focusRequest ? { nodes: [{ id: focusRequest.id }], maxZoom: 1.1, minZoom: 0.5, padding: 0.5, duration: 200 } : {}}
        />
      </SvelteFlow>
      {#if flowNodes.length <= 1}
        <!-- Overlay, NOT a Svelte Flow <Panel>: a Panel captures pointer events
             over the canvas and blocks the handles (no crosshair / no connect). -->
        <div class="empty-hint">Drag a <strong>Source</strong> from the tray to begin, then wire operations toward a <strong>View result</strong>.</div>
      {/if}
    </div>

    <aside class="preview" class:collapsed={previewCollapsed}>
      <header class="preview-head">
        {@render railToggle(previewCollapsed, "right", "preview", () => (previewCollapsed = !previewCollapsed))}
        {#if !previewCollapsed}
          <span class="preview-title">Preview</span>
          <span class="count">{preview.nodes.length} / {universe.length}</span>
        {/if}
      </header>
      {#if !previewCollapsed}
      {#if warnings.length > 0}
        <ul class="preview-warnings" role="alert">
          {#each warnings as w (w)}
            <li>⚠ {w}</li>
          {/each}
        </ul>
      {/if}
      {#snippet previewRow(node: EvalNode, ctx: RowCtx<EvalNode>)}
        <!-- A real-node parent (a Nest header that IS a node) stays a real row,
             collapsible via its own caret — tree-uniformity. `annColor` keeps the
             raw swatch token for `--tint`, matching the pane stripe treatment. -->
        <div class="prow" style={`padding-left:${11 + ctx.depth * 12}px;${annColor(node.id) ? `--tint:${annColor(node.id)}` : ""}`}>
          {#if ctx.collapsible}
            <RowCaret collapsed={ctx.collapsed} toggle={ctx.toggle} />
          {/if}
          {node.title}
          {#if ctx.collapsible}<span class="prow-count">{ctx.childCount}</span>{/if}
        </div>
      {/snippet}
      <div class="preview-list">
        {#if universe.length === 0}
          <p class="preview-empty">No <code>{kind}</code> nodes in this project to preview.</p>
        {:else}
          <ViewNodeList result={preview} mode="tree" row={previewRow}>
            {#snippet whenEmpty()}
              <p class="preview-empty">No matches — the current expression selects nothing.</p>
            {/snippet}
          </ViewNodeList>
        {/if}
      </div>
      {/if}
    </aside>
  </div>
</section>

<style>
  .view-designer {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--panel);
  }
  .designer-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .kind-pick {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .kind-fixed {
    padding: 3px 6px;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
  }
  /* A tray you pick from (§240): serif group labels; glyph-chips on a liftable
     surface. Footprint ≈ the old dense toolbar — the invitation comes from the
     treatment, not extra size. No per-chip stripe: the glyph carries the kind. */
  .palette {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .pal-group {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
  }
  .pal-label {
    font-family: var(--serif);
    font-size: var(--fs-sm);
    color: var(--text-2);
    width: 74px;
    flex-shrink: 0;
  }
  .pal-chips {
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
  }
  .palette button.chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text);
    cursor: grab;
    transition: transform var(--t-fast), box-shadow var(--t-fast), border-color var(--t-fast);
  }
  .palette button.chip:hover {
    transform: translateY(-1px);
    box-shadow: var(--elev-1);
    border-color: var(--accent);
  }
  .palette button.chip:active {
    cursor: grabbing;
    transform: none;
    box-shadow: none;
  }
  .chip-g {
    display: inline-flex;
    align-items: center;
  }
  .chip-drag {
    color: var(--text-3);
    font-size: var(--fs-xs);
    letter-spacing: -2px;
    opacity: 0;
    transition: opacity var(--t-fast);
  }
  .palette button.chip:hover .chip-drag {
    opacity: 0.6;
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
  /* Svelte Flow needs an explicitly sized parent. §G: the stock skin is retuned
     onto the token layer through the library's own `--xy-*` custom-property seam
     (cleaner than fighting :global specificity, and it themes both modes at once
     since the tokens are already theme-aware). The stock stylesheet stays
     imported for layout/behavior only. */
  .canvas :global(.svelte-flow) {
    height: 100%;
    /* flat writing-desk board, no dot grid (§1.3) */
    --xy-background-color: var(--board);
    /* the node wrapper paints nothing — each .vnode owns its own surface */
    --xy-node-background-color: transparent;
    --xy-node-border: none;
    --xy-node-boxshadow-hover: none;
    --xy-node-boxshadow-selected: none;
    /* wires */
    /* node-set wires take the accent (kind-tinted, §240), softened via opacity
       on the path below so they read as calm pipes, not hard rules */
    --xy-edge-stroke: var(--accent);
    --xy-edge-stroke-selected: var(--accent);
    /* ports (the generic `.port` rule paints the hollow ring on top of this) */
    --xy-handle-background-color: var(--surface);
    --xy-handle-border-color: var(--accent);
    /* zoom/fit controls */
    --xy-controls-button-background-color: var(--panel);
    --xy-controls-button-background-color-hover: var(--inset);
    --xy-controls-button-border-color: var(--border);
    --xy-controls-button-color: var(--text-2);
    --xy-controls-button-color-hover: var(--text);
    --xy-controls-box-shadow: var(--elev-1);
    /* rubber-band selection box + the low-key attribution chip */
    --xy-selection-background-color: var(--accent-soft);
    --xy-selection-border: 1px dashed var(--accent);
    --xy-attribution-background-color: transparent;
  }
  /* Edges a touch heavier than the 1px default so wiring reads clearly, incl.
     the in-progress connection line and the custom self-loop (BaseEdge). */
  .canvas :global(.svelte-flow__edge-path),
  .canvas :global(.svelte-flow__connection-path) {
    stroke-width: 2;
    /* softened accent so the node-set wire reads as a calm pipe (§240) */
    stroke-opacity: 0.6;
  }
  /* The value-set wire (ADR-0031 §D): a scalar `field_of` projection. Dashed +
     tinted `--k-snippet` (matching the value handles) so it reads as a visibly
     different pipe from the solid, neutral node-set wires — and distinct from the
     `--k-lore` Nest children port it used to clash with. */
  .canvas :global(.svelte-flow__edge.value-wire .svelte-flow__edge-path) {
    stroke: var(--k-snippet);
    stroke-opacity: 0.85;
    stroke-dasharray: 5 4;
  }
  .empty-hint {
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 4;
    /* Must not intercept pointer events — the handles live under it. */
    pointer-events: none;
    background: var(--inset);
    border: 1px dashed var(--border-strong);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  /* Parameters rail (§D): a left aside mirroring the preview's chrome. A fixed
     220px when open (even with no params — the empty state shows a one-line hint);
     collapsed it shrinks to just the toggle, costing the canvas almost no width. */
  .params-rail {
    width: 220px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--inset);
    overflow-y: auto;
  }
  .params-rail.collapsed {
    width: auto;
  }
  .params-rail.collapsed .params-head {
    border-bottom: none;
  }
  .params-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
  }
  .params-title {
    flex: 1;
  }
  .rail-toggle {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
  }
  .rail-toggle:hover {
    color: var(--text);
  }
  .params-empty {
    margin: 0;
    padding: 10px 12px;
    font-size: var(--fs-xs);
    line-height: 1.4;
    color: var(--text-3);
  }
  .params-list {
    margin: 0;
    padding: 6px;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .param-row {
    display: grid;
    grid-template-columns: auto 1fr auto;
    grid-template-areas:
      "mark label type"
      "mark default default";
    gap: 2px 8px;
    width: 100%;
    text-align: left;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    background: var(--panel);
    padding: 6px 8px;
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .param-row:hover {
    border-color: var(--border-strong);
    background: var(--accent-soft);
  }
  .param-mark {
    grid-area: mark;
    align-self: center;
    display: inline-flex;
  }
  .param-label {
    grid-area: label;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .param-type {
    grid-area: type;
    align-self: center;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .param-default {
    grid-area: default;
    overflow: hidden;
    font-size: var(--fs-xs);
    color: var(--text-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .param-row.unbound .param-default {
    color: var(--text-3);
    font-style: italic;
  }
  .preview {
    width: 260px;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--inset);
  }
  /* Collapsed: the aside folds to a thin strip holding only the toggle, giving
     the canvas the full width (#220). */
  .preview.collapsed {
    width: auto;
  }
  .preview.collapsed .preview-head {
    border-bottom: none;
  }
  .preview-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
  }
  .preview-title {
    flex: 1;
  }
  .count {
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }
  .preview-warnings {
    margin: 0;
    padding: 6px 12px;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--warn);
    background: var(--warn-soft);
    border-bottom: 1px solid var(--border);
  }
  .preview-list {
    flex: 1;
    overflow-y: auto;
    padding: 6px;
  }
  .preview-empty {
    padding: 12px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .prow {
    padding: 4px 8px 4px 11px;
    font-size: var(--fs-sm);
    border-left: 3px solid var(--tint, transparent);
    border-radius: var(--r-sm);
  }
  .prow:hover {
    background: var(--panel);
  }
  .prow-count {
    margin-left: 6px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
  }
</style>
