import { getContext, setContext } from "svelte";
import type { PlotBoardCard, PlotPointClaim } from "@/lib/types";

export type PlotBoardContext = {
  saving: boolean;
  selectedCardId: string | null;
  selectedClaimId: string | null;
  selectedColumnId: string | null;
  dragOverCardId: string | null;
  cardById: (cardId: string) => PlotBoardCard | null;
  cardColumnTitle: (cardId: string) => string;
  claimsForCard: (cardId: string) => PlotPointClaim[];
  selectColumn: (columnId: string) => void;
  addCardToColumn: (columnId: string) => void;
  pointLabel: (claim: PlotPointClaim) => string;
  selectCard: (cardId: string) => void;
  selectClaim: (claim: PlotPointClaim) => void;
  dragClaim: (claim: PlotPointClaim, event: DragEvent) => void;
  clearDragOver: () => void;
  allowCardDrop: (cardId: string, event: DragEvent) => void;
  leaveCardDrop: (cardId: string, event: DragEvent) => void;
  dropOnCard: (cardId: string, event: DragEvent) => void;
  removeClaim: (claim: PlotPointClaim, event: MouseEvent) => void;
  openCardNode: (card: PlotBoardCard, event: MouseEvent) => void;
  promoteCard: (card: PlotBoardCard, event: MouseEvent) => void;
};

const KEY = Symbol("plot-board-context");

export function setPlotBoardContext(getter: () => PlotBoardContext): void {
  setContext(KEY, getter);
}

export function usePlotBoardContext(): () => PlotBoardContext {
  return getContext<() => PlotBoardContext>(KEY);
}
