<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import "./PlotBoardBodyView.css";
  import { SvelteFlow, Controls, MiniMap, type Connection, type Edge, type Node as FlowNode, type OnMoveEnd, type Viewport } from "@xyflow/svelte";
  import { untrack } from "svelte";
  import { api } from "@/lib/api";
  import { setStructure } from "@/lib/stores/structure";
  import { isLeafNode } from "@/lib/utils/treeHelpers";
  import PlotBoardFlowCard from "./PlotBoardFlowCard.svelte";
  import { setPlotBoardContext } from "./plotBoardContext";
  import type {
    EditableDocument,
    PlotBoardCard,
    PlotBoardLayout,
    PlotBoardSpec,
    PlotContextClaim,
    PlotContextPacket,
    PlotNode,
    PlotNodeSummary,
    PlotPointClaim,
    PlotRelationship,
    PlotTemplateInstancePoint,
    StructureDocument,
    StructureNode,
  } from "@/lib/types";

  interface Props {
    scene?: EditableDocument | null;
    structure?: StructureDocument | null;
    onFocus?: () => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
    onSaved?: (plot: PlotNode) => void;
  }

  let {
    scene = null,
    structure = null,
    onFocus,
    onNavigate,
    onSaved,
  }: Props = $props();

  type BoardColumn = {
    id: string;
    title: string;
    cards: PlotBoardCard[];
  };

  type TemplatePointRow = {
    instance: PlotNode;
    point: PlotTemplateInstancePoint;
    status: "missing" | "partial" | "used";
    claim: PlotPointClaim | null;
  };

  type PlotDragPayload =
    | { kind: "plot-point"; template_instance_id: string; plot_point_id: string }
    | { kind: "plot-claim"; claim_id: string };

  type PlotFlowData = { cardId: string };
  type CanvasPoint = { x: number; y: number };

  const PLOT_DND_TYPE = "application/x-local-writing-plot";
  const CARD_NODE_WIDTH = 250;
  const CARD_ROW_HEIGHT = 170;
  const CARD_COLUMN_WIDTH = 310;
  const DEFAULT_VIEWPORT: Viewport = { x: 24, y: 24, zoom: 1 };
  const nodeTypes = { plotCard: PlotBoardFlowCard };
  const CLAIM_TYPE_OPTIONS: { value: PlotPointClaim["claim_type"]; label: string }[] = [
    { value: "satisfies", label: "Satisfies" },
    { value: "partially_satisfies", label: "Partially satisfies" },
    { value: "subverts", label: "Subverts" },
    { value: "foreshadows", label: "Foreshadows" },
    { value: "pays_off", label: "Pays off" },
    { value: "raises_question", label: "Raises question" },
    { value: "rejects", label: "Rejects" },
    { value: "custom", label: "Custom" },
  ];
  const CLAIM_STRENGTH_OPTIONS: { value: "" | NonNullable<PlotPointClaim["strength"]>; label: string }[] = [
    { value: "", label: "Not set" },
    { value: "weak", label: "Weak" },
    { value: "medium", label: "Medium" },
    { value: "strong", label: "Strong" },
  ];

  const EMPTY_BOARD = {
    version: 1,
    template_instance_ids: [],
    plotlines: [],
    cards: [],
    claims: [],
    relationships: [],
    metadata: {},
  };

  let selectedCardId = $state<string | null>(null);
  let selectedClaimId = $state<string | null>(null);
  let selectedPalettePoint = $state<string | null>(null);
  let templateFilterId = $state("");
  let templateToAddId = $state("");
  let templateInstances: PlotNode[] = $state([]);
  let availableTemplates: PlotNodeSummary[] = $state([]);
  let templateLoadError = $state("");
  let templateRequest = 0;
  let loadedPlotId = $state<string | null>(null);
  let loadedPlotRevision = $state<string | null>(null);
  let localPlotNode = $state<PlotNode | null>(null);
  let savingMessage = $state("");
  let saveError = $state("");
  let dragOverCardId = $state<string | null>(null);
  let includeFutureContext = $state(false);
  let plotContext = $state<PlotContextPacket | null>(null);
  let plotContextLoading = $state(false);
  let plotContextError = $state("");
  let plotContextRequest = 0;
  let flowNodes: FlowNode<PlotFlowData>[] = $state([]);
  let flowEdges: Edge[] = $state([]);
  let flowViewport = $state<Viewport>(DEFAULT_VIEWPORT);
  let canvasHydrating = false;
  let lastCanvasSnapshot = "";

  let plotNode = $derived(localPlotNode ?? asPlotNode(scene));
  let board = $derived(plotNode?.board ?? EMPTY_BOARD);
  let instanceIds = $derived.by(() => {
    const ids = new Set<string>();
    for (const id of board.template_instance_ids ?? []) ids.add(id);
    for (const line of board.plotlines ?? []) {
      if (line.template_instance_id) ids.add(line.template_instance_id);
    }
    for (const claim of board.claims ?? []) ids.add(claim.template_instance_id);
    return [...ids];
  });
  let cards = $derived(board.cards ?? []);
  let claims = $derived(board.claims ?? []);
  let claimsByCard = $derived.by(() => {
    const map = new Map<string, PlotPointClaim[]>();
    for (const claim of claims) {
      const list = map.get(claim.card_id) ?? [];
      list.push(claim);
      map.set(claim.card_id, list);
    }
    return map;
  });
  let instanceById = $derived.by(() => new Map(templateInstances.map((node) => [node.id, node])));
  let selectedCard = $derived(cards.find((card) => card.id === selectedCardId) ?? null);
  let selectedClaim = $derived(claims.find((claim) => claim.id === selectedClaimId) ?? null);
  let visibleTemplateInstances = $derived(
    templateFilterId ? templateInstances.filter((node) => node.id === templateFilterId) : templateInstances,
  );
  let paletteRows = $derived.by<TemplatePointRow[]>(() => {
    const rows: TemplatePointRow[] = [];
    for (const instance of visibleTemplateInstances) {
      for (const point of instance.template_instance?.plot_points ?? []) {
        const claim = claims.find(
          (candidate) =>
            candidate.template_instance_id === instance.id &&
            candidate.plot_point_id === point.plot_point_id,
        ) ?? null;
        rows.push({
          instance,
          point,
          claim,
          status: claim ? (claim.claim_type === "partially_satisfies" ? "partial" : "used") : "missing",
        });
      }
    }
    return rows;
  });
  let columns = $derived(buildColumns(structure, cards));
  let structureColumnOptions = $derived(flattenStructure(structure?.root));
  let selectedPointLabel = $derived(selectedClaim ? pointLabel(selectedClaim) : "");
  let selectedContextSceneId = $derived(selectedCard?.node_ref ?? null);
  let selectedPaletteRow = $derived(
    selectedPalettePoint
      ? paletteRows.find((row) => selectedPalettePoint === pointKey(row.instance.id, row.point.plot_point_id)) ?? null
      : null,
  );

  setPlotBoardContext(() => ({
    saving: Boolean(savingMessage),
    selectedCardId,
    selectedClaimId,
    dragOverCardId,
    cardById,
    claimsForCard,
    pointLabel,
    selectCard,
    selectClaim,
    dragClaim,
    clearDragOver,
    allowCardDrop,
    leaveCardDrop,
    dropOnCard,
    removeClaim,
    openCardNode,
    promoteCard,
  }));

  $effect(() => {
    const incoming = asPlotNode(scene);
    const id = incoming?.id ?? null;
    const revision = incoming?.revision ?? null;
    if (id === loadedPlotId && revision === loadedPlotRevision) return;
    const sameNode = Boolean(id && id === loadedPlotId);
    loadedPlotId = id;
    loadedPlotRevision = revision;
    localPlotNode = incoming;

    const nextCards = incoming?.board?.cards ?? [];
    const nextClaims = incoming?.board?.claims ?? [];
    if (!sameNode) {
      selectedCardId = nextCards[0]?.id ?? null;
      selectedClaimId = null;
      selectedPalettePoint = null;
      return;
    }

    if (selectedClaimId) {
      const claim = nextClaims.find((candidate) => candidate.id === selectedClaimId);
      if (claim) {
        selectedCardId = claim.card_id;
        selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
        return;
      }
      selectedClaimId = null;
    }

    if (selectedCardId && nextCards.some((card) => card.id === selectedCardId)) return;
    if (selectedPalettePoint) return;
    selectedCardId = nextCards[0]?.id ?? null;
  });

  $effect(() => {
    const id = plotNode?.id ?? null;
    if (!id) {
      availableTemplates = [];
      return;
    }
    let cancelled = false;
    void api.listPlotNodes().then((list) => {
      if (cancelled) return;
      availableTemplates = list.entries.filter((entry) => entry.entry_type === "plot:template");
      if (!templateToAddId) templateToAddId = availableTemplates[0]?.id ?? "";
    }).catch(() => {
      if (!cancelled) availableTemplates = [];
    });
    return () => {
      cancelled = true;
    };
  });

  $effect(() => {
    const ids = instanceIds;
    const req = ++templateRequest;
    templateLoadError = "";
    if (ids.length === 0) {
      templateInstances = [];
      return;
    }
    void Promise.all(
      ids.map((id) =>
        api.getPlotNode(id).catch(() => null),
      ),
    ).then((nodes) => {
      if (req !== templateRequest) return;
      templateInstances = nodes.filter((node): node is PlotNode => Boolean(node));
      if (templateInstances.length !== ids.length) {
        templateLoadError = "Some template instances could not be loaded.";
      }
    });
  });

  $effect(() => {
    const boardId = plotNode?.id ?? "";
    const boardRevision = plotNode?.revision ?? "";
    const sceneId = selectedContextSceneId;
    const includeFuture = includeFutureContext;
    const req = ++plotContextRequest;
    plotContext = null;
    plotContextError = "";
    if (!boardId) {
      plotContextLoading = false;
      return;
    }
    plotContextLoading = true;
    void api.getPlotContext(boardId, {
      scene_id: sceneId,
      include_future: includeFuture,
    }).then((context) => {
      if (req !== plotContextRequest) return;
      plotContext = context;
    }).catch((caught) => {
      if (req !== plotContextRequest) return;
      plotContextError = caught instanceof Error ? caught.message : "Could not load plot context.";
    }).finally(() => {
      if (req === plotContextRequest) plotContextLoading = false;
    });
    void boardRevision;
  });

  $effect(() => {
    const id = plotNode?.id ?? "";
    const revision = plotNode?.revision ?? "";
    const cardIds = cards.map((card) => card.id).join("|");
    const relationshipIds = (board.relationships ?? []).map((rel) => rel.id).join("|");
    canvasHydrating = true;
    flowViewport = plotNode?.layout?.viewport ?? DEFAULT_VIEWPORT;
    flowNodes = buildFlowNodes(cards, columns, plotNode?.layout ?? null);
    flowEdges = buildFlowEdges(board.relationships ?? [], cards);
    lastCanvasSnapshot = untrack(() => canvasSnapshot(flowViewport));
    queueMicrotask(() => (canvasHydrating = false));
    void id;
    void revision;
    void cardIds;
    void relationshipIds;
  });

  function asPlotNode(document: EditableDocument | null | undefined): PlotNode | null {
    if (!document || !("board" in document)) return null;
    return document as PlotNode;
  }

  function flattenStructure(root: StructureNode | null | undefined, depth = 0, acc: { id: string; title: string; depth: number }[] = []) {
    if (!root) return acc;
    if (depth > 0 && !isLeafNode(root)) acc.push({ id: root.id, title: root.title, depth });
    for (const child of root.children ?? []) flattenStructure(child, depth + 1, acc);
    return acc;
  }

  function buildColumns(currentStructure: StructureDocument | null, currentCards: PlotBoardCard[]): BoardColumn[] {
    const cardsByColumn = new Map<string, PlotBoardCard[]>();
    for (const card of currentCards) {
      const id = card.structure_column_id || "__unplaced";
      const list = cardsByColumn.get(id) ?? [];
      list.push(card);
      cardsByColumn.set(id, list);
    }

    const out: BoardColumn[] = [];
    const unplacedCards = cardsByColumn.get("__unplaced") ?? [];
    cardsByColumn.delete("__unplaced");
    out.push({
      id: "__unplaced",
      title: "Unplaced",
      cards: unplacedCards,
    });

    const structureColumns = flattenStructure(currentStructure?.root);
    for (const column of structureColumns) {
      out.push({
        id: column.id,
        title: column.title,
        cards: cardsByColumn.get(column.id) ?? [],
      });
      cardsByColumn.delete(column.id);
    }

    for (const [id, columnCards] of cardsByColumn.entries()) {
      out.push({
        id,
        title: id,
        cards: columnCards,
      });
    }

    if (out.length === 0) {
      return [{ id: "__unplaced", title: "Unplaced", cards: [] }];
    }
    return out;
  }

  function pointLabel(claim: PlotPointClaim): string {
    if (claim.claim_label) return claim.claim_label;
    const instance = instanceById.get(claim.template_instance_id);
    const point = instance?.template_instance?.plot_points?.find((candidate) => candidate.plot_point_id === claim.plot_point_id);
    return point?.title || claim.plot_point_id;
  }

  function contextPointLabel(claim: PlotContextClaim): string {
    for (const instance of plotContext?.template_instances ?? []) {
      if (instance.id !== claim.template_instance_id) continue;
      const point = instance.plot_points.find((candidate) => candidate.plot_point_id === claim.plot_point_id);
      if (point?.title) return point.title;
    }
    return claim.claim_label || claim.plot_point_id;
  }

  function contextClaimsForCard(cardId: string): PlotContextClaim[] {
    return (plotContext?.claims ?? []).filter((claim) => claim.card_id === cardId);
  }

  function omittedCount(key: string): number {
    return plotContext?.omitted_counts?.[key] ?? 0;
  }

  function pointKey(instanceId: string, pointId: string): string {
    return `${instanceId}:${pointId}`;
  }

  function cardById(cardId: string): PlotBoardCard | null {
    return cards.find((card) => card.id === cardId) ?? null;
  }

  function claimsForCard(cardId: string): PlotPointClaim[] {
    return claimsByCard.get(cardId) ?? [];
  }

  function selectCard(cardId: string): void {
    selectedCardId = cardId;
    selectedClaimId = null;
    selectedPalettePoint = null;
    onFocus?.();
  }

  function selectClaim(claim: PlotPointClaim): void {
    selectedCardId = claim.card_id;
    selectedClaimId = claim.id;
    selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    onFocus?.();
  }

  function selectPalettePoint(row: TemplatePointRow): void {
    selectedPalettePoint = pointKey(row.instance.id, row.point.plot_point_id);
    if (row.claim) {
      selectClaim(row.claim);
      return;
    }
    selectedCardId = null;
    selectedClaimId = null;
    onFocus?.();
  }

  function setPlotDragPayload(event: DragEvent, payload: PlotDragPayload): void {
    const transfer = event.dataTransfer;
    if (!transfer) return;
    const encoded = JSON.stringify(payload);
    transfer.setData(PLOT_DND_TYPE, encoded);
    transfer.setData("text/plain", encoded);
    transfer.effectAllowed = payload.kind === "plot-claim" ? "move" : "copy";
  }

  function readPlotDragPayload(event: DragEvent): PlotDragPayload | null {
    const transfer = event.dataTransfer;
    if (!transfer) return null;
    const raw = transfer.getData(PLOT_DND_TYPE) || transfer.getData("text/plain");
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as Partial<PlotDragPayload>;
      if (
        parsed.kind === "plot-point" &&
        typeof parsed.template_instance_id === "string" &&
        typeof parsed.plot_point_id === "string"
      ) {
        return {
          kind: "plot-point",
          template_instance_id: parsed.template_instance_id,
          plot_point_id: parsed.plot_point_id,
        };
      }
      if (parsed.kind === "plot-claim" && typeof parsed.claim_id === "string") {
        return { kind: "plot-claim", claim_id: parsed.claim_id };
      }
    } catch {
      return null;
    }
    return null;
  }

  function dragPalettePoint(row: TemplatePointRow, event: DragEvent): void {
    selectPalettePoint(row);
    setPlotDragPayload(event, {
      kind: "plot-point",
      template_instance_id: row.instance.id,
      plot_point_id: row.point.plot_point_id,
    });
  }

  function dragClaim(claim: PlotPointClaim, event: DragEvent): void {
    event.stopPropagation();
    selectClaim(claim);
    setPlotDragPayload(event, { kind: "plot-claim", claim_id: claim.id });
  }

  function clearDragOver(): void {
    dragOverCardId = null;
  }

  function allowCardDrop(cardId: string, event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    dragOverCardId = cardId;
  }

  function leaveCardDrop(cardId: string, event: DragEvent): void {
    const current = event.currentTarget as HTMLElement;
    const next = event.relatedTarget as Node | null;
    if (dragOverCardId === cardId && (!next || !current.contains(next))) {
      dragOverCardId = null;
    }
  }

  function openCardNode(card: PlotBoardCard, event: MouseEvent): void {
    event.stopPropagation();
    if (!card.node_ref) return;
    onNavigate?.({ id: card.node_ref, kind: "scene" });
  }

  function cloneBoardSpec(source: PlotBoardSpec): PlotBoardSpec {
    return JSON.parse(JSON.stringify(source)) as PlotBoardSpec;
  }

  function newLocalId(prefix: string): string {
    const raw = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
    return `${prefix}_${raw.replace(/-/g, "").slice(0, 12)}`;
  }

  function positionFromRecord(position: Record<string, number> | undefined): CanvasPoint | null {
    const x = position?.x;
    const y = position?.y;
    return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y) ? { x, y } : null;
  }

  function defaultCardPosition(card: PlotBoardCard, currentColumns: BoardColumn[]): CanvasPoint {
    const columnIndex = Math.max(0, currentColumns.findIndex((column) => column.cards.some((candidate) => candidate.id === card.id)));
    const column = currentColumns[columnIndex];
    const rowIndex = Math.max(0, column?.cards.findIndex((candidate) => candidate.id === card.id) ?? 0);
    return {
      x: columnIndex * CARD_COLUMN_WIDTH,
      y: rowIndex * CARD_ROW_HEIGHT,
    };
  }

  function buildFlowNodes(currentCards: PlotBoardCard[], currentColumns: BoardColumn[], layout: PlotBoardLayout | null): FlowNode<PlotFlowData>[] {
    const layoutById = new Map((layout?.nodes ?? []).map((node) => [node.id, node]));
    const currentById = new Map(untrack(() => flowNodes).map((node) => [node.id, node]));
    return currentCards.map((card) => {
      const persisted = positionFromRecord(layoutById.get(card.id)?.position);
      const current = currentById.get(card.id)?.position;
      return {
        id: card.id,
        type: "plotCard",
        position: persisted ?? current ?? defaultCardPosition(card, currentColumns),
        data: { cardId: card.id },
        width: CARD_NODE_WIDTH,
      };
    });
  }

  function relationshipLabel(relationship: PlotRelationship): string {
    return relationship.label || relationship.kind.replace(/_/g, " ");
  }

  function buildFlowEdges(relationships: PlotRelationship[], currentCards: PlotBoardCard[]): Edge[] {
    const cardIds = new Set(currentCards.map((card) => card.id));
    return relationships
      .filter((relationship) => cardIds.has(relationship.from_card_id) && cardIds.has(relationship.to_card_id))
      .map((relationship) => ({
        id: relationship.id,
        source: relationship.from_card_id,
        target: relationship.to_card_id,
        sourceHandle: "out",
        targetHandle: "in",
        label: relationshipLabel(relationship),
        class: `relationship-edge ${relationship.kind}`,
      }));
  }

  function toLayout(viewport: Viewport = flowViewport): PlotBoardLayout {
    return {
      nodes: flowNodes.map((node) => ({
        id: node.id,
        kind: "card",
        position: { x: node.position.x, y: node.position.y },
        cfg: {},
      })),
      edges: flowEdges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        source_handle: edge.sourceHandle ?? null,
        target_handle: edge.targetHandle ?? null,
      })),
      viewport,
    };
  }

  function canvasSnapshot(viewport: Viewport = flowViewport): string {
    return JSON.stringify(toLayout(viewport));
  }

  async function persistPlot(nextBoard: PlotBoardSpec, nextLayout: PlotBoardLayout | null, message: string): Promise<PlotNode | null> {
    if (!plotNode) return null;
    savingMessage = message;
    saveError = "";
    try {
      const saved = await api.savePlotNode(plotNode.id, {
        title: plotNode.title,
        entry_type: plotNode.entry_type,
        body: plotNode.body ?? "",
        metadata: plotNode.metadata ?? {},
        template: plotNode.template ?? null,
        template_instance: plotNode.template_instance ?? null,
        board: nextBoard,
        layout: nextLayout,
        base_revision: plotNode.revision,
      });
      localPlotNode = saved;
      onSaved?.(saved);
      return saved;
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not save plot board.";
      return null;
    } finally {
      savingMessage = "";
    }
  }

  async function persistBoard(nextBoard: PlotBoardSpec, message: string): Promise<PlotNode | null> {
    return persistPlot(nextBoard, toLayout(), message);
  }

  async function persistCanvas(viewport: Viewport = flowViewport): Promise<void> {
    if (!plotNode || canvasHydrating) return;
    const snapshot = canvasSnapshot(viewport);
    if (snapshot === lastCanvasSnapshot) return;
    const saved = await persistPlot(board, toLayout(viewport), "Saving layout");
    if (saved) lastCanvasSnapshot = snapshot;
  }

  function optionalText(value: string): string | null {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }

  async function updateSelectedCard(patch: Partial<PlotBoardCard>, message = "Saving card"): Promise<void> {
    const card = selectedCard;
    if (!card || savingMessage) return;
    const nextBoard = cloneBoardSpec(board);
    nextBoard.cards = (nextBoard.cards ?? []).map((candidate) =>
      candidate.id === card.id ? { ...candidate, ...patch } : candidate,
    );
    await persistBoard(nextBoard, message);
  }

  async function updateSelectedClaim(patch: Partial<PlotPointClaim>, message = "Saving claim"): Promise<void> {
    const claim = selectedClaim;
    if (!claim || savingMessage) return;
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = (nextBoard.claims ?? []).map((candidate) =>
      candidate.id === claim.id ? { ...candidate, ...patch } : candidate,
    );
    await persistBoard(nextBoard, message);
  }

  function commitCardTitle(event: Event): void {
    const value = (event.currentTarget as HTMLInputElement).value.trim();
    if (!selectedCard || !value || value === selectedCard.title) return;
    void updateSelectedCard({ title: value });
  }

  function commitCardSynopsis(event: Event): void {
    const value = (event.currentTarget as HTMLTextAreaElement).value;
    if (!selectedCard || value === selectedCard.synopsis) return;
    void updateSelectedCard({ synopsis: value });
  }

  function changeCardColumn(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value;
    const structureColumnId = value === "__unplaced" ? null : value;
    if (!selectedCard || (selectedCard.structure_column_id ?? null) === structureColumnId) return;
    void updateSelectedCard({ structure_column_id: structureColumnId });
  }

  function changeCardPlotline(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value;
    const plotlineId = value || null;
    if (!selectedCard || (selectedCard.primary_plotline_id ?? null) === plotlineId) return;
    void updateSelectedCard({ primary_plotline_id: plotlineId });
  }

  function commitClaimLabel(event: Event): void {
    const value = optionalText((event.currentTarget as HTMLInputElement).value);
    if (!selectedClaim || (selectedClaim.claim_label ?? null) === value) return;
    void updateSelectedClaim({ claim_label: value });
  }

  function changeClaimType(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value as PlotPointClaim["claim_type"];
    if (!selectedClaim || selectedClaim.claim_type === value) return;
    void updateSelectedClaim({ claim_type: value });
  }

  function changeClaimStrength(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value as "" | NonNullable<PlotPointClaim["strength"]>;
    const strength = value || null;
    if (!selectedClaim || (selectedClaim.strength ?? null) === strength) return;
    void updateSelectedClaim({ strength });
  }

  function changeClaimPlotline(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value;
    const plotlineId = value || null;
    if (!selectedClaim || (selectedClaim.plotline_id ?? null) === plotlineId) return;
    void updateSelectedClaim({ plotline_id: plotlineId });
  }

  function commitClaimTextField(field: "evidence" | "rationale" | "ai_notes", event: Event): void {
    const value = optionalText((event.currentTarget as HTMLTextAreaElement).value);
    if (!selectedClaim || (selectedClaim[field] ?? null) === value) return;
    void updateSelectedClaim({ [field]: value });
  }

  async function addTemplateInstance(): Promise<void> {
    if (!templateToAddId) return;
    savingMessage = "Adding template instance";
    saveError = "";
    try {
      const template = await api.getPlotNode(templateToAddId);
      const instance = await api.createPlotNode({
        title: `${template.title} plot`,
        entry_type: "plot:template_instance",
        body: template.body ?? "",
        metadata: {},
        template_instance: {
          template_id: template.id,
          plot_points: (template.template?.plot_points ?? []).map((point) => ({
            plot_point_id: point.id,
            title: point.title,
            function_claim: point.function_claim,
            notes: "",
            metadata: { ...(point.metadata ?? {}) },
          })),
          metadata: {},
        },
      });
      const nextBoard = cloneBoardSpec(board);
      if (!nextBoard.template_instance_ids.includes(instance.id)) {
        nextBoard.template_instance_ids = [...nextBoard.template_instance_ids, instance.id];
      }
      nextBoard.plotlines = [
        ...nextBoard.plotlines,
        {
          id: newLocalId("plotline"),
          title: instance.title,
          template_instance_id: instance.id,
          color: null,
          metadata: {},
        },
      ];
      const saved = await persistBoard(nextBoard, "Adding template instance");
      if (!saved) {
        try {
          await api.deletePlotNode(instance.id);
        } catch {
          saveError = `${saveError || "Could not link template instance to board."} The new template instance could not be cleaned up automatically.`;
        }
        return;
      }
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not add template instance.";
    } finally {
      savingMessage = "";
    }
  }

  function plotlineIdForInstance(templateInstanceId: string): string | null {
    return board.plotlines.find((line) => line.template_instance_id === templateInstanceId)?.id ?? null;
  }

  async function attachPointToCard(cardId: string, templateInstanceId: string, plotPointId: string): Promise<void> {
    if (savingMessage) return;
    const nextClaim: PlotPointClaim = {
      id: newLocalId("claim"),
      card_id: cardId,
      template_instance_id: templateInstanceId,
      plot_point_id: plotPointId,
      plotline_id: plotlineIdForInstance(templateInstanceId),
      claim_type: "satisfies",
      claim_label: null,
      strength: null,
      confidence: null,
      evidence: null,
      rationale: null,
      ai_notes: null,
      metadata: {},
    };
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = [...(nextBoard.claims ?? []), nextClaim];
    const saved = await persistBoard(nextBoard, "Attaching function point");
    if (saved) {
      selectedCardId = cardId;
      selectedClaimId = nextClaim.id;
      selectedPalettePoint = pointKey(templateInstanceId, plotPointId);
    }
  }

  async function moveClaimToCard(claimId: string, cardId: string): Promise<void> {
    if (savingMessage) return;
    const claim = claims.find((candidate) => candidate.id === claimId);
    if (!claim) return;
    if (claim.card_id === cardId) {
      selectClaim(claim);
      return;
    }
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = (nextBoard.claims ?? []).map((candidate) =>
      candidate.id === claimId ? { ...candidate, card_id: cardId } : candidate,
    );
    const saved = await persistBoard(nextBoard, "Moving claim");
    if (saved) {
      selectedCardId = cardId;
      selectedClaimId = claimId;
      selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    }
  }

  async function removeClaim(claim: PlotPointClaim, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    if (savingMessage) return;
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = (nextBoard.claims ?? []).filter((candidate) => candidate.id !== claim.id);
    const saved = await persistBoard(nextBoard, "Removing claim");
    if (saved) {
      selectedClaimId = null;
      selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    }
  }

  async function dropOnCard(cardId: string, event: DragEvent): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    dragOverCardId = null;
    const payload = readPlotDragPayload(event);
    if (!payload) return;
    if (payload.kind === "plot-claim") {
      await moveClaimToCard(payload.claim_id, cardId);
      return;
    }
    await attachPointToCard(cardId, payload.template_instance_id, payload.plot_point_id);
  }

  async function addPlaceholderCard(columnId: string | null): Promise<void> {
    const title = window.prompt("Card title", "New plot card")?.trim();
    if (!title) return;
    const card: PlotBoardCard = {
      id: newLocalId("card"),
      title,
      synopsis: "",
      structure_column_id: columnId === "__unplaced" ? null : columnId,
      node_ref: null,
      primary_plotline_id: null,
      metadata: {},
    };
    const nextBoard = cloneBoardSpec(board);
    nextBoard.cards = [...nextBoard.cards, card];
    const saved = await persistBoard(nextBoard, "Adding card");
    if (saved) {
      selectedCardId = card.id;
      selectedClaimId = null;
      selectedPalettePoint = null;
    }
  }

  async function promoteCard(card: PlotBoardCard, event?: MouseEvent): Promise<void> {
    event?.stopPropagation();
    if (!plotNode || card.node_ref || savingMessage) return;
    saveError = "";
    savingMessage = "Promoting card";
    try {
      const response = await api.promotePlotCard(plotNode.id, {
        card_id: card.id,
        title: card.title,
        parent_id: card.structure_column_id ?? null,
        base_revision: plotNode.revision,
      });
      localPlotNode = response.plot;
      onSaved?.(response.plot);
      setStructure(response.structure);
      selectedCardId = card.id;
      selectedClaimId = null;
      selectedPalettePoint = null;
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not promote card.";
    } finally {
      savingMessage = "";
    }
  }

  async function addChapter(): Promise<void> {
    const title = window.prompt("Chapter title", "New chapter")?.trim();
    if (!title) return;
    saveError = "";
    savingMessage = "Adding chapter";
    try {
      setStructure(await api.createStructureNode(title, "scene:chapter"));
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not add chapter.";
    } finally {
      savingMessage = "";
    }
  }

  const handleMoveEnd: OnMoveEnd = (_, viewport) => {
    flowViewport = viewport;
    void persistCanvas(viewport);
  };

  function handleNodeDragStop(): void {
    void persistCanvas();
  }

  function connectRelationship(connection: Connection): void {
    if (!connection.source || !connection.target || connection.source === connection.target || savingMessage) return;
    const relationship: PlotRelationship = {
      id: newLocalId("relationship"),
      from_card_id: connection.source,
      to_card_id: connection.target,
      kind: "causes",
      label: null,
      metadata: {},
    };
    const nextBoard = cloneBoardSpec(board);
    nextBoard.relationships = [...(nextBoard.relationships ?? []), relationship];
    flowEdges = buildFlowEdges(nextBoard.relationships, cards);
    void persistBoard(nextBoard, "Adding relationship");
  }
</script>

<section class="plot-board" onfocusin={() => onFocus?.()}>
  <aside class="plot-palette" aria-label="Plot template instances">
    <div class="add-template">
      <label class="filter-label">
        Add instance
        <select bind:value={templateToAddId}>
          {#each availableTemplates as template (template.id)}
            <option value={template.id}>{template.title}</option>
          {/each}
        </select>
      </label>
      <button
        type="button"
        class="tool-button icon-only"
        title="Add template instance"
        aria-label="Add template instance"
        disabled={!templateToAddId || Boolean(savingMessage)}
        onclick={() => addTemplateInstance()}
      >
        <i class="ti ti-copy-plus" aria-hidden="true"></i>
      </button>
    </div>

    <label class="filter-label template-filter">
      Template
      <select bind:value={templateFilterId}>
        <option value="">All template instances</option>
        {#each templateInstances as instance (instance.id)}
          <option value={instance.id}>{instance.title}</option>
        {/each}
      </select>
    </label>

    <div class="palette-list">
      {#if templateLoadError}
        <p class="muted-line">{templateLoadError}</p>
      {/if}
      {#if visibleTemplateInstances.length === 0}
        <p class="muted-line">No template instances on this board.</p>
      {:else}
        {#each visibleTemplateInstances as instance (instance.id)}
          <section class="template-block">
            <header>
              <strong>{instance.title}</strong>
              <span>{instance.template_instance?.plot_points?.length ?? 0}</span>
            </header>
            {#each paletteRows.filter((row) => row.instance.id === instance.id) as row (row.point.plot_point_id)}
              <button
                type="button"
                class="point-row"
                class:selected={selectedPalettePoint === pointKey(row.instance.id, row.point.plot_point_id)}
                draggable={true}
                onclick={() => selectPalettePoint(row)}
                ondragstart={(event) => dragPalettePoint(row, event)}
                ondragend={() => {
                  dragOverCardId = null;
                }}
              >
                <span class="point-title">{row.point.title || row.point.plot_point_id}</span>
                <span class:used={row.status === "used"} class:partial={row.status === "partial"} class:missing={row.status === "missing"}>
                  {row.status}
                </span>
              </button>
            {/each}
          </section>
        {/each}
      {/if}
    </div>
  </aside>

  <main class="plot-canvas" aria-label="Plot board cards">
    <div class="board-toolbar">
      <span>{cards.length} cards</span>
      <span>{claims.length} claims</span>
      <span>{board.relationships.length} relationships</span>
      {#if savingMessage}
        <span>{savingMessage}…</span>
      {/if}
      {#if saveError}
        <span class="toolbar-error">{saveError}</span>
      {/if}
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addPlaceholderCard(null)}>
        <i class="ti ti-note" aria-hidden="true"></i>
        Card
      </button>
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addChapter()}>
        <i class="ti ti-library-plus" aria-hidden="true"></i>
        Chapter
      </button>
    </div>
    <div class="flow-canvas">
      <SvelteFlow
        bind:nodes={flowNodes}
        bind:edges={flowEdges}
        bind:viewport={flowViewport}
        {nodeTypes}
        onconnect={connectRelationship}
        onnodedragstop={handleNodeDragStop}
        onmoveend={handleMoveEnd}
        fitView
        minZoom={0.25}
        maxZoom={1.8}
      >
        <Controls />
        <MiniMap pannable zoomable nodeColor="var(--accent)" nodeStrokeColor="var(--border-strong)" />
      </SvelteFlow>
      {#if cards.length === 0}
        <div class="empty-hint">Add a card to start mapping the board.</div>
      {/if}
    </div>
  </main>

  <aside class="plot-inspector" aria-label="Plot selection">
    {#if selectedClaim}
      <header class="inspector-head">
        <span>Claim</span>
        <strong>{selectedPointLabel}</strong>
      </header>
      <div class="inspector-form">
        <label>
          Label override
          <input
            value={selectedClaim.claim_label ?? ""}
            placeholder={selectedPointLabel}
            disabled={Boolean(savingMessage)}
            onblur={commitClaimLabel}
          />
        </label>
        <label>
          Card
          <input value={selectedCard?.title ?? selectedClaim.card_id} disabled />
        </label>
        <label>
          Type
          <select value={selectedClaim.claim_type} disabled={Boolean(savingMessage)} onchange={changeClaimType}>
            {#each CLAIM_TYPE_OPTIONS as option (option.value)}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </label>
        <label>
          Strength
          <select value={selectedClaim.strength ?? ""} disabled={Boolean(savingMessage)} onchange={changeClaimStrength}>
            {#each CLAIM_STRENGTH_OPTIONS as option (option.value)}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </label>
        {#if board.plotlines.length > 0}
          <label>
            Plotline
            <select value={selectedClaim.plotline_id ?? ""} disabled={Boolean(savingMessage)} onchange={changeClaimPlotline}>
              <option value="">None</option>
              {#each board.plotlines as line (line.id)}
                <option value={line.id}>{line.title}</option>
              {/each}
            </select>
          </label>
        {/if}
        <label>
          Specific rationale
          <textarea
            rows="4"
            value={selectedClaim.rationale ?? ""}
            disabled={Boolean(savingMessage)}
            onblur={(event) => commitClaimTextField("rationale", event)}
          ></textarea>
        </label>
        <label>
          Evidence
          <textarea
            rows="3"
            value={selectedClaim.evidence ?? ""}
            disabled={Boolean(savingMessage)}
            onblur={(event) => commitClaimTextField("evidence", event)}
          ></textarea>
        </label>
        <label>
          AI notes
          <textarea
            rows="3"
            value={selectedClaim.ai_notes ?? ""}
            disabled={Boolean(savingMessage)}
            onblur={(event) => commitClaimTextField("ai_notes", event)}
          ></textarea>
        </label>
      </div>
    {:else if selectedCard}
      <header class="inspector-head">
        <span>Card</span>
        <strong>{selectedCard.title}</strong>
      </header>
      <div class="inspector-form">
        <label>
          Title
          <input value={selectedCard.title} disabled={Boolean(savingMessage)} onblur={commitCardTitle} />
        </label>
        <label>
          Synopsis
          <textarea
            rows="5"
            value={selectedCard.synopsis}
            disabled={Boolean(savingMessage)}
            onblur={commitCardSynopsis}
          ></textarea>
        </label>
        <label>
          Manuscript position
          <select value={selectedCard.structure_column_id ?? "__unplaced"} disabled={Boolean(savingMessage)} onchange={changeCardColumn}>
            <option value="__unplaced">Unplaced</option>
            {#each structureColumnOptions as column (column.id)}
              <option value={column.id}>{"\u00a0".repeat(Math.max(0, column.depth - 1) * 2)}{column.title}</option>
            {/each}
          </select>
        </label>
        {#if board.plotlines.length > 0}
          <label>
            Primary plotline
            <select value={selectedCard.primary_plotline_id ?? ""} disabled={Boolean(savingMessage)} onchange={changeCardPlotline}>
              <option value="">None</option>
              {#each board.plotlines as line (line.id)}
                <option value={line.id}>{line.title}</option>
              {/each}
            </select>
          </label>
        {/if}
        <div class="inspector-stat">
          <span>Claims</span>
          <strong>{(claimsByCard.get(selectedCard.id) ?? []).length}</strong>
        </div>
        {#if selectedCard.node_ref}
          <div class="inspector-stat">
            <span>Draft node</span>
            <button type="button" class="link-button" onclick={(event) => selectedCard && openCardNode(selectedCard, event)}>
              {selectedCard.node_ref}
              <i class="ti ti-arrow-up-right" aria-hidden="true"></i>
            </button>
          </div>
        {:else}
          <button
            type="button"
            class="tool-button inspector-action"
            disabled={Boolean(savingMessage)}
            onclick={(event) => selectedCard && promoteCard(selectedCard, event)}
          >
            <i class="ti ti-file-plus" aria-hidden="true"></i>
            Promote to scene
          </button>
        {/if}
      </div>
    {:else if selectedPaletteRow}
      <header class="inspector-head">
        <span>Function point</span>
        <strong>{selectedPaletteRow.point.title || selectedPaletteRow.point.plot_point_id}</strong>
      </header>
      <dl>
        <dt>Template instance</dt>
        <dd>{selectedPaletteRow.instance.title}</dd>
        <dt>Status</dt>
        <dd>{selectedPaletteRow.status}</dd>
        {#if selectedPaletteRow.point.function_claim}
          <dt>Function claim</dt>
          <dd>{selectedPaletteRow.point.function_claim}</dd>
        {/if}
        {#if selectedPaletteRow.point.notes}
          <dt>Notes</dt>
          <dd>{selectedPaletteRow.point.notes}</dd>
        {/if}
      </dl>
    {:else}
      <p class="muted-line">No card selected.</p>
    {/if}

    {#if plotNode}
      <section class="context-preview" aria-label="AI plot context">
        <header>
          <span>AI context</span>
          <label>
            <input type="checkbox" bind:checked={includeFutureContext} />
            Future
          </label>
        </header>
        {#if plotContextLoading}
          <p class="muted-line">Loading…</p>
        {:else if plotContextError}
          <p class="context-error">{plotContextError}</p>
        {:else if !selectedContextSceneId && !includeFutureContext}
          <p class="muted-line">No draft scene scope.</p>
        {:else if plotContext}
          <div class="context-stats">
            <span>{plotContext.cards.length} cards</span>
            <span>{plotContext.claims.length} claims</span>
            <span>{omittedCount("future_cards")} future</span>
          </div>
          {#if plotContext.cards.length === 0}
            <p class="muted-line">No visible plot cards.</p>
          {:else}
            <div class="context-card-list">
              {#each plotContext.cards as contextCard (contextCard.id)}
                <article class="context-card">
                  <header>
                    <strong>{contextCard.title}</strong>
                    {#if contextCard.structure_title}
                      <span>{contextCard.structure_title}</span>
                    {/if}
                  </header>
                  {#if contextCard.synopsis}
                    <p>{contextCard.synopsis}</p>
                  {/if}
                  {#if contextClaimsForCard(contextCard.id).length > 0}
                    <ul>
                      {#each contextClaimsForCard(contextCard.id) as contextClaim (contextClaim.id)}
                        <li>
                          <span>{contextPointLabel(contextClaim)}</span>
                          <small>{contextClaim.claim_type}</small>
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </article>
              {/each}
            </div>
          {/if}
        {/if}
      </section>
    {/if}
  </aside>
</section>
