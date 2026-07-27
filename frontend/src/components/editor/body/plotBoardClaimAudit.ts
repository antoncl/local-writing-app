import { api } from "@/lib/api";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import type {
  NodePickerRef,
  PlotBoardCard,
  PlotNode,
  PlotPointClaim,
  PlotTemplateInstancePoint,
} from "@/lib/types";

const PLOT_CLAIM_AUDIT_PROMPT_ID = "prompt_builtin_plot_claim_audit";

type TemplatePointRowLike = {
  instance: PlotNode;
  point: PlotTemplateInstancePoint;
};

type PlotClaimAuditContext = {
  plotNode: PlotNode | null;
  selectedClaim: PlotPointClaim | null;
  selectedCard: PlotBoardCard | null;
  selectedPaletteRow: TemplatePointRowLike | null;
  selectedPointLabel: string;
  cardById: (cardId: string) => PlotBoardCard | null;
};

function plotBoardRef(plotNode: PlotNode | null): NodePickerRef | null {
  if (!plotNode) return null;
  return {
    id: plotNode.id,
    kind: "plot",
    title: plotNode.title || "Plot board",
    entry_type: plotNode.entry_type,
  };
}

function selectedAuditFocus(context: PlotClaimAuditContext): string {
  const { plotNode, selectedClaim, selectedCard, selectedPaletteRow, selectedPointLabel, cardById } = context;
  const boardTitle = plotNode?.title || "this plot board";
  if (selectedClaim) {
    const card = cardById(selectedClaim.card_id);
    const beatTitle = selectedPointLabel || selectedClaim.plot_point_id;
    const assignment = selectedClaim.claim_type.replace(/_/g, " ");
    return `Audit the "${beatTitle}" function badge on card "${card?.title ?? selectedClaim.card_id}" in "${boardTitle}". Check whether the card's ${assignment} claim is supported by its rationale, evidence, synopsis, and surrounding plot context.`;
  }
  if (selectedCard) {
    return `Audit the function badges on card "${selectedCard.title}" in "${boardTitle}". Check whether the card advances the story, whether any badges are weak or unsupported, and whether the card is overloaded.`;
  }
  if (selectedPaletteRow) {
    const beatTitle = selectedPaletteRow.point.title || selectedPaletteRow.point.plot_point_id;
    return `Audit the plot beat "${beatTitle}" in "${selectedPaletteRow.instance.title}" on "${boardTitle}". Check whether the claiming cards combine to satisfy the beat, what evidence is missing, and whether untagged or nearby cards should participate.`;
  }
  return "Find weak, unsupported, duplicated, or missing plot-beat claims across the selected plot board.";
}

export async function openPlotClaimAuditChat(context: PlotClaimAuditContext): Promise<void> {
  const ref = plotBoardRef(context.plotNode);
  if (!ref) return;
  try {
    const prompt = (await api.listPromptEntries()).entries.find(
      (entry) => entry.id === PLOT_CLAIM_AUDIT_PROMPT_ID,
    );
    if (!prompt) throw new Error("Could not find the Plot Claim Audit prompt.");
    await chatSessions.openChatFromPromptEntry(
      prompt,
      {
        plot: [ref],
        focus: selectedAuditFocus(context),
      },
      null,
    );
  } catch (caught) {
    chatSessions.setError(`Couldn't open claim audit: ${(caught as Error).message}`);
  }
}
