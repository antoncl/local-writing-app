import { api } from "@/lib/api";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import type {
  NodePickerRef,
  PlotBoardCard,
  PlotNode,
  PlotPointClaim,
  PlotTemplateInstancePoint,
} from "@/lib/types";
import type { PlotDiagnostics } from "./plotBoardDiagnostics";

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
  diagnostics?: PlotDiagnostics;
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

export function cardAssistFocus(context: PlotClaimAuditContext): string {
  const card = context.selectedCard;
  if (!card) return selectedAuditFocus(context);
  const boardTitle = context.plotNode?.title || "this plot board";
  const cardClaims = (context.plotNode?.board?.claims ?? []).filter((claim) => claim.card_id === card.id);
  return `Help make card "${card.title}" (id: ${card.id}) stronger in "${boardTitle}". Treat diagnostics as signals, not verdicts. Current issues: ${cardAssistIssues(context, cardClaims)} Current function badges: ${cardAssistClaims(cardClaims)} Card synopsis: ${card.synopsis || "No synopsis yet."} Give concrete story repair options as draft suggestions with target ids: narrative actions, obstacles, choices, reveals, consequences, claim changes, relationship changes, or whether this should become a scene. Do not draft prose or mutate the board; offer specific options the author can choose from and later apply manually.`;
}

async function openPlotClaimChat(context: PlotClaimAuditContext, focus: string): Promise<void> {
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
        focus,
      },
      null,
    );
  } catch (caught) {
    chatSessions.setError(`Couldn't open claim audit: ${(caught as Error).message}`);
  }
}

function cardAssistIssues(context: PlotClaimAuditContext, cardClaims: PlotPointClaim[]): string {
  const cardDiagnostics = context.selectedCard ? context.diagnostics?.cards.get(context.selectedCard.id) ?? [] : [];
  const claimDiagnostics = cardClaims.flatMap((claim) => context.diagnostics?.claims.get(claim.id) ?? []);
  return [...cardDiagnostics, ...claimDiagnostics].map((item) => item.label).join("; ") || "No explicit diagnostics are marked, but the card can still be strengthened.";
}

function cardAssistClaims(cardClaims: PlotPointClaim[]): string {
  if (cardClaims.length === 0) return "The card has no function badges yet.";
  return cardClaims.map((claim) => `${claim.claim_label || claim.plot_point_id} [${claim.id}] (${claim.claim_type}${claim.strength ? `, ${claim.strength}` : ""})`).join("; ");
}

export async function openPlotClaimAuditChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotClaimChat(context, selectedAuditFocus(context));
}

export async function openPlotCardAssistChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotClaimChat(context, cardAssistFocus(context));
}
