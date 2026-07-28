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

const PLOT_BRAINSTORM_PROMPT_ID = "prompt_builtin_plot_brainstorm";
const PLOT_CLAIM_AUDIT_PROMPT_ID = "prompt_builtin_plot_claim_audit";

type TemplatePointRowLike = {
  instance: PlotNode;
  point: PlotTemplateInstancePoint;
  status?: "missing" | "partial" | "used";
  claims?: PlotPointClaim[];
};

type PlotClaimAuditContext = {
  plotNode: PlotNode | null;
  selectedClaim: PlotPointClaim | null;
  selectedCard: PlotBoardCard | null;
  selectedPaletteRow: TemplatePointRowLike | null;
  paletteRows?: TemplatePointRowLike[];
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
    return `Review the "${beatTitle}" story marker on card "${card?.title ?? selectedClaim.card_id}" in "${boardTitle}". Check whether the card's ${assignment} marker is supported by its rationale, evidence, synopsis, and surrounding plot context.`;
  }
  if (selectedCard) {
    return `Review the story markers on card "${selectedCard.title}" in "${boardTitle}". Check whether the card advances the story, whether any markers are weak or unsupported, and whether the card is overloaded.`;
  }
  if (selectedPaletteRow) {
    const beatTitle = selectedPaletteRow.point.title || selectedPaletteRow.point.plot_point_id;
    return `Review the story beat "${beatTitle}" in "${selectedPaletteRow.instance.title}" on "${boardTitle}". Check whether the supporting cards combine to satisfy the beat, what evidence is missing, and whether untagged or nearby cards should participate.`;
  }
  return "Find weak, unsupported, duplicated, or missing story markers across the selected plot board.";
}

export function cardAssistFocus(context: PlotClaimAuditContext): string {
  const card = context.selectedCard;
  if (!card) return selectedAuditFocus(context);
  const boardTitle = context.plotNode?.title || "this plot board";
  const cardClaims = (context.plotNode?.board?.claims ?? []).filter((claim) => claim.card_id === card.id);
  return `Help make card "${card.title}" (id: ${card.id}) stronger in "${boardTitle}". Treat diagnostics as signals, not verdicts. Current issues: ${cardAssistIssues(context, cardClaims)} Current story markers: ${cardAssistClaims(cardClaims)} Card synopsis: ${card.synopsis || "No synopsis yet."} Give concrete story repair options as draft suggestions with target ids: narrative actions, obstacles, choices, reveals, consequences, story marker changes, relationship changes, or whether this should become a scene. Do not draft prose or mutate the board; offer specific options the author can choose from and later apply manually.`;
}

export function untaggedCardAssistFocus(context: PlotClaimAuditContext): string {
  const card = context.selectedCard;
  if (!card) return selectedAuditFocus(context);
  const boardTitle = context.plotNode?.title || "this plot board";
  return `Help decide what story function card "${card.title}" (id: ${card.id}) could serve in "${boardTitle}". The card currently has no story markers. Treat that as a useful question, not a verdict. Card synopsis: ${card.synopsis || "No synopsis yet."} Candidate plot beats: ${candidateBeatSummary(context)} Offer concrete options the author can choose from: existing plot beats this card could support, a better card synopsis if the current one is too vague, or a reason this card may be connective tissue rather than a plot beat carrier. When suggesting a marker, emit a new_claim draft suggestion with target_card_id="${card.id}", target_claim_id="", and the exact template_instance_id and plot_point_id from the candidate beat. Put why the card supports the beat in rationale_to_add and what evidence would make it convincing in evidence_to_add. Do not invent template ids or mutate the board.`;
}

export function boardIdeationFocus(context: PlotClaimAuditContext): string {
  const boardTitle = context.plotNode?.title || "this plot board";
  const cardCount = context.plotNode?.board?.cards?.length ?? 0;
  const markerCount = context.plotNode?.board?.claims?.length ?? 0;
  const issueCount = context.diagnostics?.summary.total ?? 0;
  return `Brainstorm ways to simplify and strengthen "${boardTitle}". Current board shape: ${countLabel(cardCount, "card")}, ${countLabel(markerCount, "story marker")}, ${countLabel(issueCount, "diagnostic check")}. Offer a few concrete structure options the author can choose from: cards to add, split, merge, move, or clarify; story markers to add, remove, or strengthen; act/chapter placement ideas; and questions that unlock the next writing decision. Favor practical next steps over terminology or critique.`;
}

export function beatAssistFocus(context: PlotClaimAuditContext): string {
  const row = context.selectedPaletteRow;
  if (!row) return boardIdeationFocus(context);
  const boardTitle = context.plotNode?.title || "this plot board";
  const beatTitle = row.point.title || row.point.plot_point_id;
  const markerClaims = row.claims ?? (context.plotNode?.board?.claims ?? []).filter(
    (claim) =>
      claim.template_instance_id === row.instance.id &&
      claim.plot_point_id === row.point.plot_point_id,
  );
  const markerSummary = markerClaims.length === 0
    ? "No cards currently claim to support this beat."
    : markerClaims
        .map((claim) => {
          const card = context.cardById(claim.card_id);
          return `${claim.claim_label || card?.title || claim.card_id} [${claim.id}] on "${card?.title ?? claim.card_id}" (${claim.claim_type}${claim.strength ? `, ${claim.strength}` : ""})`;
        })
        .join("; ");
  const diagnostics = context.diagnostics?.points.get(`${row.instance.id}:${row.point.plot_point_id}`)?.map((item) => item.label).join("; ") || "No explicit diagnostics are marked.";
  return `Help the author make the plot beat "${beatTitle}" feel earned in "${boardTitle}". Template instance: "${row.instance.title}" (id: ${row.instance.id}). Plot beat id: ${row.point.plot_point_id}. Beat purpose: ${row.point.function_claim || "No template purpose is recorded."} Story specifics: ${row.point.notes || "No story-specific version has been written yet."} Author intent: ${row.point.author_intent || "No author intent is recorded yet."} Current board use: ${row.status ?? "unknown"}. Current story markers: ${markerSummary} Diagnostics: ${diagnostics} Offer concrete options the author can choose from: existing cards that could support this beat, missing pressure or consequence, a possible new card if needed, marker changes to add/move/strengthen, and one or two author decisions that would unlock the beat. Do not draft prose or declare final canon; give practical structure moves and draft suggestions with target ids.`;
}

function candidateBeatSummary(context: PlotClaimAuditContext): string {
  const paletteRows = context.paletteRows ?? (context.selectedPaletteRow ? [context.selectedPaletteRow] : []);
  return paletteRows.length > 0 ? beatRowsSummary(paletteRows) : "Use the plot board context to choose from available template instances and plot beats.";
}

function beatRowsSummary(rows: TemplatePointRowLike[]): string {
  return rows
    .map((row) => {
      const title = row.point.title || row.point.plot_point_id;
      const purpose = row.point.function_claim ? ` - ${row.point.function_claim}` : "";
      return `${title} [${row.instance.id}:${row.point.plot_point_id}] in "${row.instance.title}"${purpose}`;
    })
    .join("; ");
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

async function openPlotPromptChat(
  context: PlotClaimAuditContext,
  promptId: string,
  focus: string,
  failureLabel: string,
): Promise<void> {
  const ref = plotBoardRef(context.plotNode);
  if (!ref) return;
  try {
    const prompt = (await api.listPromptEntries()).entries.find(
      (entry) => entry.id === promptId,
    );
    if (!prompt) throw new Error(`Could not find the ${failureLabel} prompt.`);
    await chatSessions.openChatFromPromptEntry(
      prompt,
      {
        plot: [ref],
        focus,
      },
      null,
    );
  } catch (caught) {
    chatSessions.setError(`Couldn't open ${failureLabel.toLowerCase()}: ${(caught as Error).message}`);
  }
}

function cardAssistIssues(context: PlotClaimAuditContext, cardClaims: PlotPointClaim[]): string {
  const cardDiagnostics = context.selectedCard ? context.diagnostics?.cards.get(context.selectedCard.id) ?? [] : [];
  const claimDiagnostics = cardClaims.flatMap((claim) => context.diagnostics?.claims.get(claim.id) ?? []);
  return [...cardDiagnostics, ...claimDiagnostics].map((item) => item.label).join("; ") || "No explicit diagnostics are marked, but the card can still be strengthened.";
}

function cardAssistClaims(cardClaims: PlotPointClaim[]): string {
  if (cardClaims.length === 0) return "The card has no story markers yet.";
  return cardClaims.map((claim) => `${claim.claim_label || claim.plot_point_id} [${claim.id}] (${claim.claim_type}${claim.strength ? `, ${claim.strength}` : ""})`).join("; ");
}

export async function openPlotClaimAuditChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotPromptChat(context, PLOT_CLAIM_AUDIT_PROMPT_ID, selectedAuditFocus(context), "Plot Review");
}

export async function openPlotCardAssistChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotPromptChat(context, PLOT_CLAIM_AUDIT_PROMPT_ID, cardAssistFocus(context), "Plot Review");
}

export async function openPlotUntaggedCardAssistChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotPromptChat(context, PLOT_CLAIM_AUDIT_PROMPT_ID, untaggedCardAssistFocus(context), "Plot Review");
}

export async function openPlotBeatAssistChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotPromptChat(context, PLOT_BRAINSTORM_PROMPT_ID, beatAssistFocus(context), "Plot Brainstorm");
}

export async function openPlotBrainstormChat(context: PlotClaimAuditContext): Promise<void> {
  await openPlotPromptChat(context, PLOT_BRAINSTORM_PROMPT_ID, boardIdeationFocus(context), "Plot Brainstorm");
}
