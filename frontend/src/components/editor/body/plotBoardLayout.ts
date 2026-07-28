import type { Edge, Node as FlowNode, Viewport } from "@xyflow/svelte";

import { isLeafNode } from "@/lib/utils/treeHelpers";
import type {
  PlotBoardCard,
  PlotBoardLayout,
  PlotRelationship,
  StructureDocument,
  StructureNode,
} from "@/lib/types";

export type BoardColumn = {
  id: string;
  title: string;
  type: string;
  parentId: string | null;
  depth: number;
  cards: PlotBoardCard[];
};

export type PlotCardFlowData = { kind: "card"; cardId: string };
export type PlotGroupFlowData = {
  kind: "group";
  columnId: string;
  title: string;
  count: number;
  columnType: string;
  parentColumnId: string | null;
  minWidth: number;
  minHeight: number;
};
export type PlotFlowData = PlotCardFlowData | PlotGroupFlowData;
export type CanvasPoint = { x: number; y: number };

type GroupFrame = {
  id: string;
  parentId: string | null;
  position: CanvasPoint;
  absolute: CanvasPoint;
  width: number;
  height: number;
};

export const CARD_NODE_WIDTH = 250;
export const CARD_ROW_HEIGHT = 170;
const CARD_COLUMN_WIDTH = 310;
export const GROUP_HEADER_HEIGHT = 64;
export const GROUP_INSET = 24;
const GROUP_GAP = 30;
export const GROUP_MIN_HEIGHT = 280;
export const GROUP_MIN_WIDTH = 310;
const ROOT_GROUP_ROW_WIDTH = 1180;
export const DEFAULT_VIEWPORT: Viewport = { x: 24, y: 24, zoom: 1 };

type FlatStructureColumn = {
  id: string;
  title: string;
  type: string;
  parentId: string | null;
  depth: number;
};

export function flattenStructure(
  root: StructureNode | null | undefined,
  depth = 0,
  parentId: string | null = null,
  acc: FlatStructureColumn[] = [],
): FlatStructureColumn[] {
  if (!root) return acc;
  const isContainer = depth > 0 && !isLeafNode(root);
  if (isContainer) acc.push({ id: root.id, title: root.title, type: root.type, parentId, depth });
  for (const child of root.children ?? []) {
    flattenStructure(child, depth + 1, isContainer ? root.id : parentId, acc);
  }
  return acc;
}

export function buildColumns(
  currentStructure: StructureDocument | null,
  currentCards: PlotBoardCard[],
): BoardColumn[] {
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

function positionFromRecord(position: Record<string, number> | undefined): CanvasPoint | null {
  const x = position?.x;
  const y = position?.y;
  return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y) ? { x, y } : null;
}

function numberFromConfig(cfg: Record<string, unknown> | undefined, key: string): number | null {
  const value = cfg?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function defaultCardPosition(card: PlotBoardCard, column: BoardColumn): CanvasPoint {
  const rowIndex = Math.max(0, column.cards.findIndex((candidate) => candidate.id === card.id));
  return {
    x: GROUP_INSET,
    y: GROUP_HEADER_HEIGHT + rowIndex * CARD_ROW_HEIGHT,
  };
}

export function groupNodeId(columnId: string): string {
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

function groupDimensions(column: BoardColumn, currentColumns: BoardColumn[], layoutById: Map<string, PlotBoardLayout["nodes"][number]>): {
  width: number;
  height: number;
  minWidth: number;
  minHeight: number;
} {
  const id = groupNodeId(column.id);
  const minWidth = groupWidth(column, currentColumns);
  const minHeight = nestedGroupHeight(column, currentColumns);
  const persisted = layoutById.get(id);
  const width = column.type === "scene:act" ? Math.max(minWidth, numberFromConfig(persisted?.cfg, "width") ?? minWidth) : minWidth;
  const height = column.type === "scene:act" ? Math.max(minHeight, numberFromConfig(persisted?.cfg, "height") ?? minHeight) : minHeight;
  return { width, height, minWidth, minHeight };
}

function rootAutoPosition(width: number, height: number, cursor: { x: number; y: number; rowHeight: number }): CanvasPoint {
  if (cursor.x > 0 && cursor.x + width > ROOT_GROUP_ROW_WIDTH) {
    cursor.x = 0;
    cursor.y += cursor.rowHeight + GROUP_GAP;
    cursor.rowHeight = 0;
  }
  const position = { x: cursor.x, y: cursor.y };
  cursor.x += width + GROUP_GAP;
  cursor.rowHeight = Math.max(cursor.rowHeight, height);
  return position;
}

function buildGroupFrames(currentColumns: BoardColumn[], layout: PlotBoardLayout | null): Map<string, GroupFrame> {
  const frames = new Map<string, GroupFrame>();
  const layoutById = new Map((layout?.nodes ?? []).map((node) => [node.id, node]));
  const addFrame = (column: BoardColumn, parentFrame: GroupFrame | null, position: CanvasPoint) => {
    const id = groupNodeId(column.id);
    const { width, height } = groupDimensions(column, currentColumns, layoutById);
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
      childX += groupDimensions(child, currentColumns, layoutById).width + GROUP_GAP;
    }
  };

  const rootCursor = { x: 0, y: 0, rowHeight: 0 };
  for (const column of rootGroups(currentColumns)) {
    const id = groupNodeId(column.id);
    const { width, height } = groupDimensions(column, currentColumns, layoutById);
    const persistedPosition = positionFromRecord(layoutById.get(id)?.position);
    const autoPosition = rootAutoPosition(width, height, rootCursor);
    addFrame(column, null, persistedPosition ?? autoPosition);
  }
  return frames;
}

function nestedCardPosition(
  card: PlotBoardCard,
  column: BoardColumn,
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

export function buildFlowNodes(
  currentCards: PlotBoardCard[],
  currentColumns: BoardColumn[],
  layout: PlotBoardLayout | null,
  currentNodes: FlowNode<PlotFlowData>[],
): FlowNode<PlotFlowData>[] {
  const layoutById = new Map((layout?.nodes ?? []).map((node) => [node.id, node]));
  const currentById = new Map(currentNodes.map((node) => [node.id, node]));
  const frames = buildGroupFrames(currentColumns, layout);
  const groupNodes = currentColumns.map((column): FlowNode<PlotFlowData> => {
    const id = groupNodeId(column.id);
    const { minWidth, minHeight } = groupDimensions(column, currentColumns, layoutById);
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
        minWidth,
        minHeight,
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
      position: nestedCardPosition(card, column, frames, persisted, current),
      parentId: groupNodeId(column.id),
      data: { kind: "card", cardId: card.id },
      width: CARD_NODE_WIDTH,
      zIndex: 2,
    };
  });
  return [...groupNodes, ...cardNodes];
}

export function buildLayoutNodes(nodes: FlowNode<PlotFlowData>[]): PlotBoardLayout["nodes"] {
  return nodes
    .filter((node) => node.data.kind === "card" || (node.data.kind === "group" && node.data.columnType === "scene:act"))
    .map((node) => ({
      id: node.id,
      kind: node.data.kind,
      position: { x: node.position.x, y: node.position.y },
      cfg: node.data.kind === "group"
        ? {
            width: node.width ?? GROUP_MIN_WIDTH,
            height: node.height ?? GROUP_MIN_HEIGHT,
          }
        : {},
    }));
}

function relationshipLabel(relationship: PlotRelationship): string {
  return relationship.label || relationship.kind.replace(/_/g, " ");
}

export function buildFlowEdges(relationships: PlotRelationship[], currentCards: PlotBoardCard[]): Edge[] {
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
