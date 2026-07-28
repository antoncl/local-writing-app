import { HttpError } from "@/lib/api";
import { appendPlotSuggestionText, type PlotSuggestion } from "@/lib/plotSuggestions";
import type {
  NodePickerRef,
  PlotBoardSpec,
  PlotBoardCard,
  PlotNode,
  PlotNodeList,
  PlotNodeSummary,
  PlotPointNoteStatus,
  PlotPointClaim,
  PlotTemplateInstancePoint,
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
  applyPlotSuggestionBeatQuestion: (suggestion: PlotSuggestion) => Promise<void>;
  createPlotSuggestionBadge: (suggestion: PlotSuggestion) => Promise<void>;
  createPlotSuggestionCard: (suggestion: PlotSuggestion) => Promise<void>;
  applyPlotSuggestionBeatFields: (suggestion: PlotSuggestion) => Promise<void>;
  applyPlotSuggestionCardSynopsis: (suggestion: PlotSuggestion) => Promise<void>;
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

  async function applyPlotSuggestionCardSynopsis(suggestion: PlotSuggestion): Promise<void> {
    const targetCardId = suggestion.target_card_id.trim();
    const synopsis = suggestion.proposed_change.trim();
    if (!targetCardId || !synopsis) {
      fail("This suggestion does not identify both a target card and synopsis text.");
    }

    for (const plotId of await plotBoardCandidateIds()) {
      const plot = await loadPlotNode(plotId, "Could not load plot board.");
      const board = plot?.board;
      if (!plot || !board) continue;

      let matched = false;
      let changed = false;
      const nextCards = (board.cards ?? []).map((card) => {
        if (card.id !== targetCardId) return card;
        matched = true;
        if (card.synopsis === synopsis) return card;
        changed = true;
        return { ...card, synopsis };
      });
      if (!matched) continue;
      if (!changed) {
        options.setChatError(null);
        return;
      }

      await savePlotBoard(plot, { ...board, cards: nextCards });
      return;
    }

    fail(`Could not find card ${targetCardId} on a plot board.`);
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

  async function createPlotSuggestionCard(suggestion: PlotSuggestion): Promise<void> {
    const title = suggestion.title.trim();
    const synopsis = suggestion.proposed_change.trim();
    const templateInstanceId = suggestion.template_instance_id.trim();
    const plotPointId = suggestion.plot_point_id.trim();
    if (suggestion.target_card_id.trim() || !title || !synopsis) {
      fail("This suggestion does not identify a new card title and synopsis.");
    }
    if (Boolean(templateInstanceId) !== Boolean(plotPointId)) {
      fail("A new card badge needs both a template instance and plot beat.");
    }

    for (const plotId of await plotBoardCandidateIds()) {
      const plot = await loadPlotNode(plotId, "Could not load plot board.");
      const board = plot?.board;
      if (!plot || !board) continue;
      if (templateInstanceId) {
        if (!(board.template_instance_ids ?? []).includes(templateInstanceId)) continue;
        if (!(await templateInstanceHasPlotPoint(templateInstanceId, plotPointId))) {
          fail("Could not find that plot beat on the target template instance.");
        }
      }

      const nextCardId = newLocalId("card");
      const nextCard: PlotBoardCard = {
        id: nextCardId,
        title,
        synopsis,
        structure_column_id: null,
        node_ref: null,
        primary_plotline_id: plotlineIdForInstance(board, templateInstanceId) ?? null,
        metadata: {},
      };
      const nextClaims = [...(board.claims ?? [])];
      if (templateInstanceId) {
        nextClaims.push({
          id: newLocalId("claim"),
          card_id: nextCardId,
          template_instance_id: templateInstanceId,
          plot_point_id: plotPointId,
          plotline_id: plotlineIdForInstance(board, templateInstanceId),
          claim_type: "satisfies",
          claim_label: null,
          strength: null,
          confidence: null,
          evidence: suggestion.evidence_to_add.trim() || null,
          rationale: null,
          ai_notes: suggestion.reason.trim() || null,
          metadata: {},
        });
      }

      await savePlotBoard(plot, { ...board, cards: [...(board.cards ?? []), nextCard], claims: nextClaims });
      return;
    }

    fail("Could not find a plot board for the new card suggestion.");
  }

  async function applyPlotSuggestionBeatFields(suggestion: PlotSuggestion): Promise<void> {
    const templateInstanceId = suggestion.template_instance_id.trim();
    const plotPointId = suggestion.plot_point_id.trim();
    const patch = plotBeatPatch(suggestion);
    if (!templateInstanceId || !plotPointId || Object.keys(patch).length === 0) {
      fail("This suggestion does not identify a plot beat field update.");
    }

    const instance = await loadPlotNode(templateInstanceId, "Could not load plot template instance.");
    const templateInstance = instance?.template_instance;
    if (!instance || !templateInstance) {
      fail("Could not load the target plot template instance.");
    }

    const nextPoints = (templateInstance.plot_points ?? []).map((point) =>
      point.plot_point_id === plotPointId
        ? { ...point, ...patch, metadata: point.metadata ?? {} }
        : point,
    );
    const nextPoint = nextPoints.find((point) => point.plot_point_id === plotPointId);
    if (!nextPoint) {
      fail("Could not find that plot beat on the target template instance.");
    }

    const saved = await options.api.savePlotNode(instance.id, {
      title: instance.title,
      entry_type: instance.entry_type,
      body: instance.body ?? "",
      metadata: instance.metadata ?? {},
      template: instance.template ?? null,
      template_instance: {
        ...templateInstance,
        plot_points: nextPoints,
        point_notes: {
          ...(templateInstance.point_notes ?? {}),
          [plotPointId]: {
            ...(templateInstance.point_notes?.[plotPointId] ?? {}),
            local_label: nextPoint.local_label || nextPoint.title || "",
            notes: nextPoint.notes ?? "",
            author_intent: nextPoint.author_intent ?? "",
            expected_role: nextPoint.expected_role ?? "",
            open_questions: nextPoint.open_questions ?? [],
            status: nextPoint.status ?? "unplanned",
            metadata: nextPoint.metadata ?? {},
          },
        },
        metadata: templateInstance.metadata ?? {},
      },
      board: instance.board ?? null,
      layout: instance.layout ?? null,
      base_revision: instance.revision,
    });
    options.setChatError(null);
    await options.onPlotSaved?.(saved);
  }

  async function applyPlotSuggestionBeatQuestion(suggestion: PlotSuggestion): Promise<void> {
    const templateInstanceId = suggestion.template_instance_id.trim();
    const plotPointId = suggestion.plot_point_id.trim();
    const questions = suggestionQuestions(suggestion);
    if (!templateInstanceId || !plotPointId || questions.length === 0) {
      fail("This suggestion does not identify a plot beat question to add.");
    }

    const instance = await loadPlotNode(templateInstanceId, "Could not load plot template instance.");
    const templateInstance = instance?.template_instance;
    if (!instance || !templateInstance) {
      fail("Could not load the target plot template instance.");
    }

    let matched = false;
    let changed = false;
    const nextPoints = (templateInstance.plot_points ?? []).map((point) => {
      if (point.plot_point_id !== plotPointId) return point;
      matched = true;
      const nextQuestions = appendQuestions(point.open_questions ?? [], questions);
      if (sameQuestions(nextQuestions, point.open_questions ?? [])) return point;
      changed = true;
      return { ...point, open_questions: nextQuestions, metadata: point.metadata ?? {} };
    });
    const nextPoint = nextPoints.find((point) => point.plot_point_id === plotPointId);
    if (!matched || !nextPoint) {
      fail("Could not find that plot beat on the target template instance.");
    }
    if (!changed) {
      options.setChatError(null);
      return;
    }

    const saved = await options.api.savePlotNode(instance.id, {
      title: instance.title,
      entry_type: instance.entry_type,
      body: instance.body ?? "",
      metadata: instance.metadata ?? {},
      template: instance.template ?? null,
      template_instance: {
        ...templateInstance,
        plot_points: nextPoints,
        point_notes: {
          ...(templateInstance.point_notes ?? {}),
          [plotPointId]: {
            ...(templateInstance.point_notes?.[plotPointId] ?? {}),
            local_label: nextPoint.local_label || nextPoint.title || "",
            notes: nextPoint.notes ?? "",
            author_intent: nextPoint.author_intent ?? "",
            expected_role: nextPoint.expected_role ?? "",
            open_questions: nextPoint.open_questions ?? [],
            status: nextPoint.status ?? "unplanned",
            metadata: nextPoint.metadata ?? {},
          },
        },
        metadata: templateInstance.metadata ?? {},
      },
      board: instance.board ?? null,
      layout: instance.layout ?? null,
      base_revision: instance.revision,
    });
    options.setChatError(null);
    await options.onPlotSaved?.(saved);
  }

  function fail(message: string): never {
    options.setChatError(message);
    throw new Error(message);
  }

  return {
    applyPlotSuggestionEvidence: (suggestion) => appendPlotSuggestionClaimField(suggestion, "evidence", suggestion.evidence_to_add),
    applyPlotSuggestionNote: (suggestion) => appendPlotSuggestionClaimField(suggestion, "ai_notes", suggestion.proposed_change),
    applyPlotSuggestionBeatQuestion,
    createPlotSuggestionBadge,
    createPlotSuggestionCard,
    applyPlotSuggestionBeatFields,
    applyPlotSuggestionCardSynopsis,
  };
}

function plotBeatPatch(suggestion: PlotSuggestion): Partial<PlotTemplateInstancePoint> {
  const patch: Partial<PlotTemplateInstancePoint> = {};
  if (suggestion.story_specifics.trim()) patch.notes = suggestion.story_specifics.trim();
  if (suggestion.author_intent.trim()) patch.author_intent = suggestion.author_intent.trim();
  if (suggestion.expected_role.trim()) patch.expected_role = suggestion.expected_role.trim();
  if (suggestion.open_questions.length > 0) patch.open_questions = suggestion.open_questions;
  if (isPlotPointNoteStatus(suggestion.status)) patch.status = suggestion.status;
  return patch;
}

function isPlotPointNoteStatus(value: string): value is PlotPointNoteStatus {
  switch (value) {
    case "unplanned":
    case "planned":
    case "drafted":
    case "satisfied":
    case "intentionally_omitted":
      return true;
    default:
      return false;
  }
}

function suggestionQuestions(suggestion: PlotSuggestion): string[] {
  const questions = [...suggestion.open_questions];
  if (suggestion.proposed_change.trim()) questions.unshift(suggestion.proposed_change.trim());
  return questions.map((question) => question.trim()).filter(Boolean);
}

function appendQuestions(existing: string[], additions: string[]): string[] {
  const seen = new Set(existing.map(normalizeComparableQuestion));
  const next = [...existing];
  for (const addition of additions) {
    const comparable = normalizeComparableQuestion(addition);
    if (!comparable || seen.has(comparable)) continue;
    seen.add(comparable);
    next.push(addition);
  }
  return next;
}

function sameQuestions(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function normalizeComparableQuestion(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
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
