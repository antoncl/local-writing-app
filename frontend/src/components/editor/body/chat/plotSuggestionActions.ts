import { HttpError } from "@/lib/api";
import { appendPlotSuggestionText, type PlotSuggestion } from "@/lib/plotSuggestions";
import type {
  NodePickerRef,
  PlotBoardSpec,
  PlotNode,
  PlotNodeList,
  PlotNodeSummary,
  PlotPointClaim,
  SavePlotNodeRequest,
} from "@/lib/types";

export type PlotSuggestionActionApi = {
  listPlotNodes: () => Promise<PlotNodeList>;
  getPlotNode: (nodeId: string) => Promise<PlotNode>;
  savePlotNode: (nodeId: string, payload: SavePlotNodeRequest) => Promise<PlotNode>;
};

export type PlotSuggestionActions = {
  applyPlotSuggestionEvidence: (suggestion: PlotSuggestion) => Promise<void>;
  applyPlotSuggestionNote: (suggestion: PlotSuggestion) => Promise<void>;
  createPlotSuggestionBadge: (suggestion: PlotSuggestion) => Promise<void>;
};

type CreatePlotSuggestionActionsOptions = {
  api: PlotSuggestionActionApi;
  getChatInputDrafts: () => Record<string, string>;
  getPlotEntries: () => PlotNodeSummary[];
  onPlotSaved?: (plot: PlotNode) => void | Promise<void>;
  setChatError: (message: string | null) => void;
  newId?: (prefix: string) => string;
};

export function createPlotSuggestionActions(options: CreatePlotSuggestionActionsOptions): PlotSuggestionActions {
  const newLocalId = options.newId ?? defaultLocalId;

  async function plotBoardCandidateIds(): Promise<string[]> {
    const selectedIds = Object.values(options.getChatInputDrafts()).flatMap((value) =>
      decodeContextPickRefs(value).map((ref) => ref.id),
    );
    const knownPlotEntries = options.getPlotEntries();
    const roster = knownPlotEntries.length > 0 ? knownPlotEntries : (await options.api.listPlotNodes()).entries;
    const boardIds = roster.filter((entry) => entry.entry_type === "plot:board").map((entry) => entry.id);
    return Array.from(new Set([...selectedIds, ...boardIds]));
  }

  async function savePlotBoard(plot: PlotNode, board: PlotBoardSpec): Promise<void> {
    const saved = await options.api.savePlotNode(plot.id, {
      title: plot.title,
      entry_type: plot.entry_type,
      body: plot.body ?? "",
      metadata: plot.metadata ?? {},
      template: plot.template ?? null,
      template_instance: plot.template_instance ?? null,
      board,
      layout: plot.layout ?? null,
      base_revision: plot.revision,
    });
    options.setChatError(null);
    await options.onPlotSaved?.(saved);
  }

  async function loadPlotNode(plotId: string, fallbackMessage: string): Promise<PlotNode | null> {
    try {
      return await options.api.getPlotNode(plotId);
    } catch (error) {
      if (error instanceof HttpError && error.status === 404) return null;
      options.setChatError(error instanceof Error ? error.message : fallbackMessage);
      throw error;
    }
  }

  async function templateInstanceHasPlotPoint(templateInstanceId: string, plotPointId: string): Promise<boolean> {
    const instance = await loadPlotNode(templateInstanceId, "Could not load plot template instance.");
    return Boolean(instance?.template_instance?.plot_points?.some((point) => point.plot_point_id === plotPointId));
  }

  async function appendPlotSuggestionClaimField(
    suggestion: PlotSuggestion,
    field: "evidence" | "ai_notes",
    value: string,
  ): Promise<void> {
    const targetClaimId = suggestion.target_claim_id.trim();
    const textToAdd = value.trim();
    if (!targetClaimId || !textToAdd) {
      fail("This suggestion does not identify both a target claim and text to apply.");
    }

    for (const plotId of await plotBoardCandidateIds()) {
      const plot = await loadPlotNode(plotId, "Could not load plot board.");
      const board = plot?.board;
      if (!plot || !board) continue;

      let matched = false;
      let changed = false;
      const nextClaims = (board.claims ?? []).map((claim) => {
        if (claim.id !== targetClaimId) return claim;
        matched = true;
        const nextValue = appendPlotSuggestionText(claim[field], textToAdd);
        if (nextValue === (claim[field] ?? "")) return claim;
        changed = true;
        return { ...claim, [field]: nextValue };
      });
      if (!matched) continue;
      if (!changed) {
        options.setChatError(null);
        return;
      }

      await savePlotBoard(plot, { ...board, claims: nextClaims });
      return;
    }

    fail(`Could not find claim ${targetClaimId} on a plot board.`);
  }

  async function createPlotSuggestionBadge(suggestion: PlotSuggestion): Promise<void> {
    const targetCardId = suggestion.target_card_id.trim();
    const templateInstanceId = suggestion.template_instance_id.trim();
    const plotPointId = suggestion.plot_point_id.trim();
    if (suggestion.target_claim_id.trim() || !targetCardId || !templateInstanceId || !plotPointId) {
      fail("This suggestion does not identify a new badge target.");
    }

    for (const plotId of await plotBoardCandidateIds()) {
      const plot = await loadPlotNode(plotId, "Could not load plot board.");
      const board = plot?.board;
      if (!plot || !board) continue;
      if (!(board.cards ?? []).some((card) => card.id === targetCardId)) continue;
      if (!(board.template_instance_ids ?? []).includes(templateInstanceId)) continue;
      if (!(await templateInstanceHasPlotPoint(templateInstanceId, plotPointId))) {
        fail("Could not find that plot beat on the target template instance.");
      }

      const existing = (board.claims ?? []).find(
        (claim) =>
          claim.card_id === targetCardId &&
          claim.template_instance_id === templateInstanceId &&
          claim.plot_point_id === plotPointId,
      );
      if (existing) {
        fail("That card already has this plot beat badge.");
      }

      const nextClaim: PlotPointClaim = {
        id: newLocalId("claim"),
        card_id: targetCardId,
        template_instance_id: templateInstanceId,
        plot_point_id: plotPointId,
        plotline_id: plotlineIdForInstance(board, templateInstanceId),
        claim_type: "satisfies",
        claim_label: null,
        strength: null,
        confidence: null,
        evidence: suggestion.evidence_to_add.trim() || null,
        rationale: null,
        ai_notes: suggestion.proposed_change.trim() || null,
        metadata: {},
      };
      await savePlotBoard(plot, { ...board, claims: [...(board.claims ?? []), nextClaim] });
      return;
    }

    fail("Could not find the target card and template instance on a plot board.");
  }

  function fail(message: string): never {
    options.setChatError(message);
    throw new Error(message);
  }

  return {
    applyPlotSuggestionEvidence: (suggestion) => appendPlotSuggestionClaimField(suggestion, "evidence", suggestion.evidence_to_add),
    applyPlotSuggestionNote: (suggestion) => appendPlotSuggestionClaimField(suggestion, "ai_notes", suggestion.proposed_change),
    createPlotSuggestionBadge,
  };
}

function decodeContextPickRefs(raw: string | undefined): NodePickerRef[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is NodePickerRef =>
        item && typeof item === "object" && typeof item.id === "string" && item.kind === "plot",
    );
  } catch {
    return [];
  }
}

function plotlineIdForInstance(board: PlotBoardSpec, templateInstanceId: string): string | null {
  return board.plotlines.find((line) => line.template_instance_id === templateInstanceId)?.id ?? null;
}

function defaultLocalId(prefix: string): string {
  const raw = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `${prefix}_${raw.replace(/-/g, "").slice(0, 12)}`;
}
