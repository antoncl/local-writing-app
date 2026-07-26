<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import "./PlotBoardBodyView.css";
  import { SvelteFlow, Controls, MiniMap, type Connection, type Edge, type Node as FlowNode, type NodeTargetEventWithPointer, type OnMoveEnd, type Viewport } from "@xyflow/svelte";
  import { untrack } from "svelte";
  import { api } from "@/lib/api";
  import { setStructure } from "@/lib/stores/structure";
  import { isLeafNode } from "@/lib/utils/treeHelpers";
  import PlotBoardFlowCard from "./PlotBoardFlowCard.svelte";
  import PlotBoardFlowGroup from "./PlotBoardFlowGroup.svelte";
  import PlotBoardInspector from "./PlotBoardInspector.svelte";
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
    type: string;
    parentId: string | null;
    depth: number;
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

  type PlotCardFlowData = { kind: "card"; cardId: string };
  type PlotGroupFlowData = {
    kind: "group";
    columnId: string;
    title: string;
    count: number;
    columnType: string;
    parentColumnId: string | null;
  };
  type PlotFlowData = PlotCardFlowData | PlotGroupFlowData;
  type CanvasPoint = { x: number; y: number };
  type NodeDragStopPayload = Parameters<NodeTargetEventWithPointer<MouseEvent | TouchEvent, FlowNode<PlotFlowData>>>[0];
  type GroupFrame = {
    id: string;
    parentId: string | null;
    position: CanvasPoint;
    absolute: CanvasPoint;
    width: number;
    height: number;
  };

  const PLOT_DND_TYPE = "application/x-local-writing-plot";
  const CARD_NODE_WIDTH = 250;
  const CARD_ROW_HEIGHT = 170;
  const CARD_COLUMN_WIDTH = 310;
  const GROUP_HEADER_HEIGHT = 64;
  const GROUP_INSET = 24;
  const GROUP_GAP = 30;
  const GROUP_MIN_HEIGHT = 280;
  const GROUP_MIN_WIDTH = 310;
  const DEFAULT_VIEWPORT: Viewport = { x: 24, y: 24, zoom: 1 };
  const nodeTypes = { plotCard: PlotBoardFlowCard, plotGroup: PlotBoardFlowGroup };
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
  let selectedCanvasColumnId = $state<string | null>(null);
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
  let selectedColumnId = $derived(selectedCard ? (selectedCard.structure_column_id ?? "__unplaced") : selectedCanvasColumnId);
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
  let selectedColumn = $derived(selectedColumnId ? columns.find((column) => column.id === selectedColumnId) ?? null : null);
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
    selectedColumnId,
    dragOverCardId,
    cardById,
    cardColumnTitle,
    claimsForCard,
    selectColumn,
    addCardToColumn,
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
        templateLoadError = "Some templates could not be loaded.";
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

  function flattenStructure(
    root: StructureNode | null | undefined,
    depth = 0,
    parentId: string | null = null,
    acc: { id: string; title: string; type: string; parentId: string | null; depth: number }[] = [],
  ) {
    if (!root) return acc;
    const isContainer = depth > 0 && !isLeafNode(root);
    if (isContainer) acc.push({ id: root.id, title: root.title, type: root.type, parentId, depth });
    for (const child of root.children ?? []) {
      flattenStructure(child, depth + 1, isContainer ? root.id : parentId, acc);
    }
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
      type: "plot:unplaced",
      parentId: null,
      depth: 0,
      cards: unplacedCards,
    });

    const structureColumns = flattenStructure(currentStructure?.root);
    for (const column of structureColumns) {
      out.push({
        id: column.id,
        title: column.title,
        type: column.type,
        parentId: column.parentId,
        depth: column.depth,
        cards: cardsByColumn.get(column.id) ?? [],
      });
      cardsByColumn.delete(column.id);
    }

    for (const [id, columnCards] of cardsByColumn.entries()) {
      out.push({
        id,
        title: id,
        type: "plot:unknown_structure",
        parentId: null,
        depth: 0,
        cards: columnCards,
      });
    }

    if (out.length === 0) {
      return [{ id: "__unplaced", title: "Unplaced", type: "plot:unplaced", parentId: null, depth: 0, cards: [] }];
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

  function cardColumnTitle(cardId: string): string {
    for (const column of columns) {
      if (column.cards.some((card) => card.id === cardId)) return column.title;
    }
    return "Unplaced";
  }

  function selectColumn(columnId: string): void {
    const column = columns.find((candidate) => candidate.id === columnId);
    selectedCanvasColumnId = columnId;
    selectedCardId = column?.cards[0]?.id ?? null;
    selectedClaimId = null;
    selectedPalettePoint = null;
  }

  function addCardToColumn(columnId: string): void {
    void addPlaceholderCard(columnId);
  }

  function claimsForCard(cardId: string): PlotPointClaim[] {
    return claimsByCard.get(cardId) ?? [];
  }

  function selectCard(cardId: string): void {
    const card = cardById(cardId);
    selectedCanvasColumnId = card?.structure_column_id ?? "__unplaced";
    selectedCardId = cardId;
    selectedClaimId = null;
    selectedPalettePoint = null;
    onFocus?.();
  }

  function selectClaim(claim: PlotPointClaim): void {
    const card = cardById(claim.card_id);
    selectedCanvasColumnId = card?.structure_column_id ?? "__unplaced";
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
    selectedCanvasColumnId = null;
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
    const payload = readPlotDragPayload(event);
    if (event.dataTransfer) event.dataTransfer.dropEffect = payload?.kind === "plot-point" ? "copy" : "move";
    dragOverCardId = cardId;
  }

  function cardIdAtPoint(event: DragEvent): string | null {
    const elements = Array.from(document.querySelectorAll<HTMLElement>(".plot-card[data-card-id]"));
    for (const element of elements) {
      const rect = element.getBoundingClientRect();
      if (
        event.clientX >= rect.left &&
        event.clientX <= rect.right &&
        event.clientY >= rect.top &&
        event.clientY <= rect.bottom
      ) {
        return element.dataset.cardId ?? null;
      }
    }
    return null;
  }

  function allowCanvasDrop(event: DragEvent): void {
    const cardId = cardIdAtPoint(event);
    if (!cardId) return;
    event.preventDefault();
    const payload = readPlotDragPayload(event);
    if (event.dataTransfer) event.dataTransfer.dropEffect = payload?.kind === "plot-point" ? "copy" : "move";
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

  function defaultCardPosition(card: PlotBoardCard, column: BoardColumn): CanvasPoint {
    const rowIndex = Math.max(0, column.cards.findIndex((candidate) => candidate.id === card.id));
    return {
      x: GROUP_INSET,
      y: GROUP_HEADER_HEIGHT + rowIndex * CARD_ROW_HEIGHT,
    };
  }

  function groupNodeId(columnId: string): string {
    return `structure:${columnId}`;
  }

  function groupHeight(column: BoardColumn): number {
    return Math.max(GROUP_MIN_HEIGHT, GROUP_HEADER_HEIGHT + GROUP_INSET + Math.max(1, column.cards.length) * CARD_ROW_HEIGHT);
  }

  function groupChildren(column: BoardColumn, currentColumns: BoardColumn[]): BoardColumn[] {
    return currentColumns.filter((candidate) => candidate.parentId === column.id);
  }

  function rootGroups(currentColumns: BoardColumn[]): BoardColumn[] {
    const ids = new Set(currentColumns.map((column) => column.id));
    return currentColumns.filter((column) => column.id === "__unplaced" || !column.parentId || !ids.has(column.parentId));
  }

  function cardLaneWidth(column: BoardColumn): number {
    return column.cards.length > 0 ? CARD_COLUMN_WIDTH : 0;
  }

  function groupWidth(column: BoardColumn, currentColumns: BoardColumn[]): number {
    const children = groupChildren(column, currentColumns);
    const childWidths = children.map((child) => groupWidth(child, currentColumns));
    const laneWidths = [cardLaneWidth(column), ...childWidths].filter((width) => width > 0);
    if (laneWidths.length === 0) return GROUP_MIN_WIDTH;
    return Math.max(GROUP_MIN_WIDTH, GROUP_INSET * 2 + laneWidths.reduce((total, width) => total + width, 0) + Math.max(0, laneWidths.length - 1) * GROUP_GAP);
  }

  function nestedGroupHeight(column: BoardColumn, currentColumns: BoardColumn[]): number {
    const children = groupChildren(column, currentColumns);
    const childHeights = children.map((child) => nestedGroupHeight(child, currentColumns));
    const cardHeight = column.cards.length > 0 ? groupHeight(column) : 0;
    if (childHeights.length === 0) return cardHeight || GROUP_MIN_HEIGHT;
    return Math.max(
      GROUP_MIN_HEIGHT,
      GROUP_HEADER_HEIGHT + GROUP_INSET + Math.max(cardHeight, ...childHeights),
    );
  }

  function buildGroupFrames(currentColumns: BoardColumn[]): Map<string, GroupFrame> {
    const frames = new Map<string, GroupFrame>();
    const addFrame = (column: BoardColumn, parentFrame: GroupFrame | null, position: CanvasPoint) => {
      const id = groupNodeId(column.id);
      const width = groupWidth(column, currentColumns);
      const height = nestedGroupHeight(column, currentColumns);
      const absolute = parentFrame
        ? { x: parentFrame.absolute.x + position.x, y: parentFrame.absolute.y + position.y }
        : { ...position };
      const frame: GroupFrame = {
        id,
        parentId: parentFrame?.id ?? null,
        position,
        absolute,
        width,
        height,
      };
      frames.set(column.id, frame);

      let childX = GROUP_INSET + (column.cards.length > 0 ? CARD_COLUMN_WIDTH + GROUP_GAP : 0);
      for (const child of groupChildren(column, currentColumns)) {
        addFrame(child, frame, { x: childX, y: GROUP_HEADER_HEIGHT });
        childX += groupWidth(child, currentColumns) + GROUP_GAP;
      }
    };

    let rootX = 0;
    for (const column of rootGroups(currentColumns)) {
      const width = groupWidth(column, currentColumns);
      addFrame(column, null, { x: rootX, y: 0 });
      rootX += width + GROUP_GAP;
    }
    return frames;
  }

  function nestedCardPosition(
    card: PlotBoardCard,
    column: BoardColumn,
    currentColumns: BoardColumn[],
    frames: Map<string, GroupFrame>,
    persisted: CanvasPoint | null,
    current: FlowNode<PlotFlowData> | undefined,
  ): CanvasPoint {
    if (current?.parentId === groupNodeId(column.id)) {
      return {
        x: GROUP_INSET,
        y: Math.max(GROUP_HEADER_HEIGHT, current.position.y),
      };
    }
    const frame = frames.get(column.id);
    if (persisted) {
      const looksAbsolute = frame && persisted.x >= frame.absolute.x - GROUP_INSET;
      if (looksAbsolute) {
        return {
          x: GROUP_INSET,
          y: Math.max(GROUP_HEADER_HEIGHT, persisted.y - frame.absolute.y + GROUP_HEADER_HEIGHT),
        };
      }
      if (persisted.y >= GROUP_HEADER_HEIGHT) return { x: GROUP_INSET, y: persisted.y };
    }
    return defaultCardPosition(card, column);
  }

  function buildFlowNodes(currentCards: PlotBoardCard[], currentColumns: BoardColumn[], layout: PlotBoardLayout | null): FlowNode<PlotFlowData>[] {
    const layoutById = new Map((layout?.nodes ?? []).map((node) => [node.id, node]));
    const currentById = new Map(untrack(() => flowNodes).map((node) => [node.id, node]));
    const frames = buildGroupFrames(currentColumns);
    const groupNodes = currentColumns.map((column): FlowNode<PlotFlowData> => {
      const id = groupNodeId(column.id);
      const frame = frames.get(column.id) ?? {
        id,
        parentId: null,
        position: { x: 0, y: 0 },
        absolute: { x: 0, y: 0 },
        width: CARD_COLUMN_WIDTH,
        height: groupHeight(column),
      };
      return {
        id,
        type: "plotGroup",
        parentId: frame.parentId ?? undefined,
        position: frame.position,
        data: {
          kind: "group",
          columnId: column.id,
          title: column.title,
          count: column.cards.length,
          columnType: column.type,
          parentColumnId: column.parentId,
        },
        width: frame.width,
        height: frame.height,
        style: `width: ${frame.width}px; height: ${frame.height}px;`,
        dragHandle: ".group-drag-handle",
        zIndex: frame.parentId ? 1 : 0,
      };
    });
    const cardNodes = currentCards.map((card): FlowNode<PlotFlowData> => {
      const persisted = positionFromRecord(layoutById.get(card.id)?.position);
      const current = currentById.get(card.id);
      const columnId = card.structure_column_id ?? "__unplaced";
      const column = currentColumns.find((candidate) => candidate.id === columnId) ?? currentColumns[0];
      return {
        id: card.id,
        type: "plotCard",
        position: nestedCardPosition(card, column, currentColumns, frames, persisted, current),
        parentId: groupNodeId(column.id),
        data: { kind: "card", cardId: card.id },
        width: CARD_NODE_WIDTH,
        zIndex: 2,
      };
    });
    return [...groupNodes, ...cardNodes];
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
      nodes: flowNodes
        .filter((node) => node.data.kind === "card")
        .map((node) => ({
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

  function flowNodeById(): Map<string, FlowNode<PlotFlowData>> {
    return new Map(flowNodes.map((node) => [node.id, node]));
  }

  function nodeAbsolutePosition(node: FlowNode<PlotFlowData>, nodesById: Map<string, FlowNode<PlotFlowData>>): CanvasPoint {
    if (!node.parentId) return node.position;
    const parent = nodesById.get(node.parentId);
    if (!parent) return node.position;
    const parentPosition = nodeAbsolutePosition(parent, nodesById);
    return {
      x: parentPosition.x + node.position.x,
      y: parentPosition.y + node.position.y,
    };
  }

  function nodeCenter(node: FlowNode<PlotFlowData>, nodesById: Map<string, FlowNode<PlotFlowData>>): CanvasPoint {
    const position = nodeAbsolutePosition(node, nodesById);
    return {
      x: position.x + (node.width ?? CARD_NODE_WIDTH) / 2,
      y: position.y + (node.height ?? CARD_ROW_HEIGHT) / 2,
    };
  }

  function containsPoint(node: FlowNode<PlotFlowData>, point: CanvasPoint, nodesById: Map<string, FlowNode<PlotFlowData>>): boolean {
    const position = nodeAbsolutePosition(node, nodesById);
    const width = node.width ?? GROUP_MIN_WIDTH;
    const height = node.height ?? GROUP_MIN_HEIGHT;
    return point.x >= position.x && point.x <= position.x + width && point.y >= position.y && point.y <= position.y + height;
  }

  function smallestGroupAt(
    point: CanvasPoint,
    predicate: (node: FlowNode<PlotFlowData>) => boolean,
    nodesById: Map<string, FlowNode<PlotFlowData>>,
  ): FlowNode<PlotFlowData> | null {
    return flowNodes
      .filter((node) => node.data.kind === "group" && predicate(node) && containsPoint(node, point, nodesById))
      .sort((a, b) => ((a.width ?? GROUP_MIN_WIDTH) * (a.height ?? GROUP_MIN_HEIGHT)) - ((b.width ?? GROUP_MIN_WIDTH) * (b.height ?? GROUP_MIN_HEIGHT)))[0] ?? null;
  }

  function cardLocalPositionInGroup(
    cardNode: FlowNode<PlotFlowData>,
    targetGroup: FlowNode<PlotFlowData>,
    nodesById: Map<string, FlowNode<PlotFlowData>>,
  ): CanvasPoint {
    const cardAbsolute = nodeAbsolutePosition(cardNode, nodesById);
    const groupAbsolute = nodeAbsolutePosition(targetGroup, nodesById);
    return {
      x: GROUP_INSET,
      y: Math.max(GROUP_HEADER_HEIGHT, cardAbsolute.y - groupAbsolute.y),
    };
  }

  function normalizeCardNodePosition(cardNode: FlowNode<PlotFlowData>): void {
    flowNodes = flowNodes.map((node) =>
      node.id === cardNode.id
        ? { ...node, position: { x: GROUP_INSET, y: Math.max(GROUP_HEADER_HEIGHT, node.position.y) } }
        : node,
    );
  }

  async function moveCardToColumn(cardNode: FlowNode<PlotFlowData>, targetColumnId: string): Promise<boolean> {
    const data = cardNode.data;
    if (data.kind !== "card" || savingMessage) return false;
    const card = cards.find((candidate) => candidate.id === data.cardId);
    if (!card) return false;
    const nextStructureColumnId = targetColumnId === "__unplaced" ? null : targetColumnId;
    if ((card.structure_column_id ?? null) === nextStructureColumnId) return false;
    const nodesById = flowNodeById();
    const targetGroup = nodesById.get(groupNodeId(targetColumnId));
    if (!targetGroup) return false;
    const nextPosition = cardLocalPositionInGroup(cardNode, targetGroup, nodesById);
    flowNodes = flowNodes.map((node) =>
      node.id === cardNode.id
        ? { ...node, parentId: targetGroup.id, position: nextPosition }
        : node,
    );
    const nextBoard = cloneBoardSpec(board);
    nextBoard.cards = (nextBoard.cards ?? []).map((candidate) =>
      candidate.id === card.id ? { ...candidate, structure_column_id: nextStructureColumnId } : candidate,
    );
    const saved = await persistBoard(nextBoard, "Moving card");
    if (saved) {
      selectedCanvasColumnId = targetColumnId;
      selectedCardId = card.id;
      selectedClaimId = null;
      selectedPalettePoint = null;
    }
    return Boolean(saved);
  }

  function chapterDropPosition(chapterId: string, targetActId: string, dropX: number): number {
    const nodesById = flowNodeById();
    let position = 0;
    for (const column of columns) {
      if (column.id === chapterId || column.type !== "scene:chapter" || column.parentId !== targetActId) continue;
      const node = nodesById.get(groupNodeId(column.id));
      if (!node) continue;
      if (dropX > nodeCenter(node, nodesById).x) position += 1;
    }
    return position;
  }

  async function moveChapterToAct(chapterNode: FlowNode<PlotFlowData>, targetActId: string): Promise<boolean> {
    const data = chapterNode.data;
    if (data.kind !== "group" || data.columnType !== "scene:chapter" || savingMessage) return false;
    const position = chapterDropPosition(data.columnId, targetActId, nodeCenter(chapterNode, flowNodeById()).x);
    const currentSiblings = columns.filter((column) => column.type === "scene:chapter" && column.parentId === targetActId);
    const currentIndex = currentSiblings.findIndex((column) => column.id === data.columnId);
    if (data.parentColumnId === targetActId && currentIndex === position) return false;
    savingMessage = "Moving chapter";
    saveError = "";
    try {
      const nextStructure = await api.moveStructureNode(data.columnId, targetActId, position);
      setStructure(nextStructure);
      selectedCanvasColumnId = data.columnId;
      selectedCardId = null;
      selectedClaimId = null;
      selectedPalettePoint = null;
      return true;
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not move chapter.";
      return false;
    } finally {
      savingMessage = "";
    }
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

  async function updateSelectedClaim(patch: Partial<PlotPointClaim>, message = "Saving badge"): Promise<void> {
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
    const saved = await persistBoard(nextBoard, "Attaching badge");
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
    const saved = await persistBoard(nextBoard, "Moving badge");
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
    const saved = await persistBoard(nextBoard, "Removing badge");
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

  async function dropOnCanvas(event: DragEvent): Promise<void> {
    const cardId = cardIdAtPoint(event);
    if (!cardId) return;
    await dropOnCard(cardId, event);
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

  async function addAct(): Promise<void> {
    const title = window.prompt("Act title", "New act")?.trim();
    if (!title) return;
    saveError = "";
    savingMessage = "Adding act";
    try {
      setStructure(await api.createStructureNode(title, "scene:act"));
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not add act.";
    } finally {
      savingMessage = "";
    }
  }

  async function addChapter(): Promise<void> {
    const title = window.prompt("Chapter title", "New chapter")?.trim();
    if (!title) return;
    saveError = "";
    savingMessage = "Adding chapter";
    const parentId =
      selectedColumn?.type === "scene:act"
        ? selectedColumn.id
        : selectedColumn?.type === "scene:chapter"
          ? selectedColumn.parentId
          : null;
    try {
      setStructure(await api.createStructureNode(title, "scene:chapter", parentId));
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

  function handleNodeDragStop({ nodes }: NodeDragStopPayload): void {
    const dragged = nodes[0];
    if (!dragged) {
      void persistCanvas();
      return;
    }
    const nodesById = flowNodeById();
    const center = nodeCenter(dragged, nodesById);
    if (dragged.data.kind === "card") {
      const target = smallestGroupAt(center, () => true, nodesById);
      if (target?.data.kind === "group" && target.id !== dragged.parentId) {
        void moveCardToColumn(dragged, target.data.columnId).then((moved) => {
          if (!moved) {
            normalizeCardNodePosition(dragged);
            void persistCanvas();
          }
        });
        return;
      }
      normalizeCardNodePosition(dragged);
      void persistCanvas();
      return;
    }
    if (dragged.data.kind === "group" && dragged.data.columnType === "scene:chapter") {
      const draggedColumnId = dragged.data.columnId;
      const targetAct = smallestGroupAt(
        center,
        (node) => node.data.kind === "group" && node.data.columnType === "scene:act" && node.data.columnId !== draggedColumnId,
        nodesById,
      );
      if (targetAct?.data.kind === "group") {
        void moveChapterToAct(dragged, targetAct.data.columnId).then((moved) => {
          if (!moved) void persistCanvas();
        });
        return;
      }
    }
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
  <aside class="plot-palette" aria-label="Plot templates">
    <div class="add-template">
      <label class="filter-label">
        Add template
        <select bind:value={templateToAddId}>
          {#each availableTemplates as template (template.id)}
            <option value={template.id}>{template.title}</option>
          {/each}
        </select>
      </label>
      <button
        type="button"
        class="tool-button icon-only"
        title="Add template to board"
        aria-label="Add template to board"
        disabled={!templateToAddId || Boolean(savingMessage)}
        onclick={() => addTemplateInstance()}
      >
        <i class="ti ti-copy-plus" aria-hidden="true"></i>
      </button>
    </div>

    <label class="filter-label template-filter">
      Template
      <select bind:value={templateFilterId}>
        <option value="">All templates on board</option>
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
        <p class="muted-line">No templates on this board.</p>
      {:else}
        {#each visibleTemplateInstances as instance (instance.id)}
          <section class="template-block">
            <header>
              <strong>{instance.title}</strong>
              <span>{instance.template_instance?.plot_points?.length ?? 0} points</span>
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
      <span>{claims.length} badges</span>
      <span>{board.relationships.length} relationships</span>
      {#if savingMessage}
        <span>{savingMessage}...</span>
      {/if}
      {#if saveError}
        <span class="toolbar-error">{saveError}</span>
      {/if}
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addPlaceholderCard(null)}>
        <i class="ti ti-note" aria-hidden="true"></i>
        Card
      </button>
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addAct()}>
        <i class="ti ti-columns-3" aria-hidden="true"></i>
        Act
      </button>
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addChapter()}>
        <i class="ti ti-library-plus" aria-hidden="true"></i>
        Chapter
      </button>
    </div>
    <div class="flow-canvas" role="region" aria-label="Plot board canvas" ondragover={allowCanvasDrop} ondrop={dropOnCanvas}>
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

  <PlotBoardInspector
    {board}
    {claimsByCard}
    {contextClaimsForCard}
    {contextPointLabel}
    bind:includeFutureContext
    {omittedCount}
    {openCardNode}
    {plotContext}
    {plotContextError}
    {plotContextLoading}
    {plotNode}
    {promoteCard}
    {savingMessage}
    {selectedCard}
    {selectedClaim}
    {selectedContextSceneId}
    {selectedPaletteRow}
    {selectedPointLabel}
    {structureColumnOptions}
    {changeCardColumn}
    {changeCardPlotline}
    {changeClaimPlotline}
    {changeClaimStrength}
    {changeClaimType}
    {commitCardSynopsis}
    {commitCardTitle}
    {commitClaimLabel}
    {commitClaimTextField}
  />
</section>
