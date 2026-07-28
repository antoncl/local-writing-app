import { describe, expect, it, vi } from "vitest";
import { createPlotSuggestionActions, type PlotSuggestionActionApi } from "./plotSuggestionActions";
import type { PlotSuggestion } from "@/lib/plotSuggestions";
import type { PlotBoardSpec, PlotNode, PlotPointClaim } from "@/lib/types";

const baseSuggestion: PlotSuggestion = {
  kind: "new_claim",
  target_card_id: "card_opening",
  target_claim_id: "",
  template_instance_id: "plot_main",
  plot_point_id: "first_turn",
  title: "Add lock-in badge",
  reason: "",
  proposed_change: "Make the consequence unavoidable.",
  evidence_to_add: "Show the door closing behind her.",
  story_specifics: "",
  author_intent: "",
  expected_role: "",
  open_questions: [],
  status: "",
};

function makeClaim(patch: Partial<PlotPointClaim> = {}): PlotPointClaim {
  return {
    id: "claim_setup",
    card_id: "card_opening",
    template_instance_id: "plot_main",
    plot_point_id: "setup_pressure",
    plotline_id: "line_main",
    claim_type: "satisfies",
    claim_label: null,
    strength: null,
    confidence: null,
    evidence: null,
    rationale: null,
    ai_notes: null,
    metadata: {},
    ...patch,
  };
}

function makeBoard(claims: PlotPointClaim[] = [makeClaim()]): PlotBoardSpec {
  return {
    version: 1,
    template_instance_ids: ["plot_main"],
    plotlines: [{ id: "line_main", title: "Main plot", template_instance_id: "plot_main", metadata: {} }],
    cards: [{ id: "card_opening", title: "Opening", synopsis: "", metadata: {} }],
    claims,
    relationships: [],
    metadata: {},
  };
}

function makePlotNode(id: string, patch: Partial<PlotNode> = {}): PlotNode {
  return {
    id,
    title: id,
    revision: "rev1",
    entry_type: id === "plot_board" ? "plot:board" : "plot:template_instance",
    body: "",
    template: null,
    template_instance: null,
    board: null,
    layout: null,
    system: false,
    metadata: {},
    computed_metadata: {},
    ...patch,
  } as PlotNode;
}

function harness(nodes: Record<string, PlotNode>) {
  let chatError: string | null = null;
  const onPlotSaved = vi.fn();
  const api: PlotSuggestionActionApi = {
    listPlotNodes: vi.fn(async () => ({
      entries: [{ id: "plot_board", title: "Board", entry_type: "plot:board", system: false }],
    })),
    getPlotNode: vi.fn(async (nodeId: string) => nodes[nodeId]),
    savePlotNode: vi.fn(async (nodeId: string, payload) => {
      const saved = {
        ...nodes[nodeId],
        ...payload,
        id: nodeId,
        revision: "rev2",
        system: nodes[nodeId].system,
        computed_metadata: nodes[nodeId].computed_metadata,
      } as PlotNode;
      nodes[nodeId] = saved;
      return saved;
    }),
  };
  const actions = createPlotSuggestionActions({
    api,
    getChatInputDrafts: () => ({}),
    getPlotEntries: () => [{ id: "plot_board", title: "Board", entry_type: "plot:board", system: false }],
    setChatError: (message) => {
      chatError = message;
    },
    onPlotSaved,
    newId: (prefix) => `${prefix}_fixed`,
  });
  return { actions, api, get chatError() { return chatError; }, nodes, onPlotSaved };
}

describe("createPlotSuggestionActions", () => {
  it("appends evidence and notes to an existing claim", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([makeClaim({ id: "claim_target" })]) }),
    });
    const suggestion = { ...baseSuggestion, kind: "claim_change", target_claim_id: "claim_target" } as PlotSuggestion;

    await env.actions.applyPlotSuggestionEvidence(suggestion);
    await env.actions.applyPlotSuggestionNote(suggestion);

    const claim = env.nodes.plot_board.board?.claims[0];
    expect(claim?.evidence).toBe("Show the door closing behind her.");
    expect(claim?.ai_notes).toBe("Make the consequence unavoidable.");
    expect(env.onPlotSaved).toHaveBeenCalledTimes(2);
  });

  it("applies a card revision as replacement synopsis", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
    });

    await env.actions.applyPlotSuggestionCardSynopsis({
      ...baseSuggestion,
      kind: "card_revision",
      target_card_id: "card_opening",
      proposed_change: "Mara steals the ledger and loses her only way back.",
    });

    expect(env.nodes.plot_board.board?.cards[0]).toEqual(
      expect.objectContaining({
        id: "card_opening",
        synopsis: "Mara steals the ledger and loses her only way back.",
      }),
    );
    expect(env.onPlotSaved).toHaveBeenCalledTimes(1);
  });

  it("creates a new unplaced card from a suggestion", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
    });

    await env.actions.createPlotSuggestionCard({
      ...baseSuggestion,
      kind: "new_card",
      target_card_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Ledger theft",
      proposed_change: "Mara steals the ledger and loses her only way back.",
    });

    expect(env.nodes.plot_board.board?.cards.find((card) => card.id === "card_fixed")).toEqual(
      expect.objectContaining({
        title: "Ledger theft",
        synopsis: "Mara steals the ledger and loses her only way back.",
        structure_column_id: null,
        node_ref: null,
        primary_plotline_id: null,
      }),
    );
    expect(env.nodes.plot_board.board?.claims).toEqual([]);
    expect(env.onPlotSaved).toHaveBeenCalledTimes(1);
  });

  it("creates a new card with an initial plot beat badge", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [{ plot_point_id: "first_turn", title: "First turn", function_claim: "", notes: "", metadata: {} }],
          metadata: {},
        },
      }),
    });

    await env.actions.createPlotSuggestionCard({
      ...baseSuggestion,
      kind: "new_card",
      target_card_id: "",
      title: "Ledger theft",
      proposed_change: "Mara steals the ledger and loses her only way back.",
      evidence_to_add: "The archive doors lock behind her.",
      reason: "This makes the first turn concrete.",
    });

    expect(env.nodes.plot_board.board?.cards.find((card) => card.id === "card_fixed")).toEqual(
      expect.objectContaining({
        title: "Ledger theft",
        primary_plotline_id: "line_main",
      }),
    );
    expect(env.nodes.plot_board.board?.claims).toEqual([
      expect.objectContaining({
        id: "claim_fixed",
        card_id: "card_fixed",
        template_instance_id: "plot_main",
        plot_point_id: "first_turn",
        plotline_id: "line_main",
        evidence: "The archive doors lock behind her.",
        ai_notes: "This makes the first turn concrete.",
      }),
    ]);
  });

  it("refuses new card suggestions with half-specified initial badge targets", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
    });

    await expect(
      env.actions.createPlotSuggestionCard({
        ...baseSuggestion,
        kind: "new_card",
        target_card_id: "",
        template_instance_id: "plot_main",
        plot_point_id: "",
        title: "Ledger theft",
        proposed_change: "Mara steals the ledger.",
      }),
    ).rejects.toThrow("A new card badge needs both a template instance and plot beat.");
    expect(env.api.savePlotNode).not.toHaveBeenCalled();
  });

  it("refuses card synopsis updates when the target card is missing", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
    });

    await expect(
      env.actions.applyPlotSuggestionCardSynopsis({
        ...baseSuggestion,
        kind: "card_revision",
        target_card_id: "card_missing",
        proposed_change: "A concrete replacement synopsis.",
      }),
    ).rejects.toThrow("Could not find card card_missing on a plot board.");
    expect(env.api.savePlotNode).not.toHaveBeenCalled();
  });

  it("creates a satisfies badge with evidence and AI notes", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [{ plot_point_id: "first_turn", title: "First turn", function_claim: "", notes: "", metadata: {} }],
          metadata: {},
        },
      }),
    });

    await env.actions.createPlotSuggestionBadge(baseSuggestion);

    expect(env.nodes.plot_board.board?.claims).toEqual([
      expect.objectContaining({
        id: "claim_fixed",
        card_id: "card_opening",
        template_instance_id: "plot_main",
        plot_point_id: "first_turn",
        plotline_id: "line_main",
        claim_type: "satisfies",
        evidence: "Show the door closing behind her.",
        ai_notes: "Make the consequence unavoidable.",
      }),
    ]);
  });

  it("refuses duplicate badges", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", {
        board: makeBoard([makeClaim({ plot_point_id: "first_turn" })]),
      }),
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [{ plot_point_id: "first_turn", title: "First turn", function_claim: "", notes: "", metadata: {} }],
          metadata: {},
        },
      }),
    });

    await expect(env.actions.createPlotSuggestionBadge(baseSuggestion)).rejects.toThrow(
      "That card already has this plot beat badge.",
    );
    expect(env.chatError).toBe("That card already has this plot beat badge.");
    expect(env.api.savePlotNode).not.toHaveBeenCalled();
  });

  it("refuses badge creation when the plot beat is not on the template instance", async () => {
    const env = harness({
      plot_board: makePlotNode("plot_board", { board: makeBoard([]) }),
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [{ plot_point_id: "setup_pressure", title: "Setup", function_claim: "", notes: "", metadata: {} }],
          metadata: {},
        },
      }),
    });

    await expect(env.actions.createPlotSuggestionBadge(baseSuggestion)).rejects.toThrow(
      "Could not find that plot beat on the target template instance.",
    );
    expect(env.chatError).toBe("Could not find that plot beat on the target template instance.");
    expect(env.api.savePlotNode).not.toHaveBeenCalled();
  });

  it("applies story-specific fields to a target plot beat", async () => {
    const env = harness({
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [
            {
              plot_point_id: "first_turn",
              title: "First turn",
              function_claim: "Makes the old path unavailable.",
              notes: "",
              author_intent: "",
              expected_role: "",
              open_questions: [],
              status: "unplanned",
              metadata: {},
            },
          ],
          point_notes: {},
          metadata: {},
        },
      }),
    });

    await env.actions.applyPlotSuggestionBeatFields({
      ...baseSuggestion,
      kind: "beat_revision",
      target_card_id: "",
      story_specifics: "Mara burns the bridge back to the archive.",
      author_intent: "Commit her to theft over loyalty.",
      expected_role: "Make retreat emotionally impossible.",
      open_questions: ["Who witnesses the break?"],
      status: "planned",
    });

    const point = env.nodes.plot_main.template_instance?.plot_points?.[0];
    expect(point).toEqual(
      expect.objectContaining({
        notes: "Mara burns the bridge back to the archive.",
        author_intent: "Commit her to theft over loyalty.",
        expected_role: "Make retreat emotionally impossible.",
        open_questions: ["Who witnesses the break?"],
        status: "planned",
      }),
    );
    expect(env.nodes.plot_main.template_instance?.point_notes?.first_turn).toEqual(
      expect.objectContaining({
        notes: "Mara burns the bridge back to the archive.",
        author_intent: "Commit her to theft over loyalty.",
        expected_role: "Make retreat emotionally impossible.",
        open_questions: ["Who witnesses the break?"],
        status: "planned",
      }),
    );
    expect(env.onPlotSaved).toHaveBeenCalledTimes(1);
  });

  it("adds question suggestions to a target plot beat without replacing existing questions", async () => {
    const env = harness({
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [
            {
              plot_point_id: "first_turn",
              title: "First turn",
              function_claim: "Makes the old path unavailable.",
              notes: "Mara burns the bridge back to the archive.",
              author_intent: "",
              expected_role: "",
              open_questions: ["Who witnesses the break?"],
              status: "planned",
              metadata: {},
            },
          ],
          point_notes: {
            first_turn: {
              notes: "Mara burns the bridge back to the archive.",
              open_questions: ["Who witnesses the break?"],
            },
          },
          metadata: {},
        },
      }),
    });

    await env.actions.applyPlotSuggestionBeatQuestion({
      ...baseSuggestion,
      kind: "question",
      target_card_id: "",
      proposed_change: "What does it cost immediately?",
      open_questions: ["Who witnesses the break?", "What can Mara no longer undo?"],
    });

    const point = env.nodes.plot_main.template_instance?.plot_points?.[0];
    expect(point).toEqual(
      expect.objectContaining({
        notes: "Mara burns the bridge back to the archive.",
        open_questions: [
          "Who witnesses the break?",
          "What does it cost immediately?",
          "What can Mara no longer undo?",
        ],
      }),
    );
    expect(env.nodes.plot_main.template_instance?.point_notes?.first_turn).toEqual(
      expect.objectContaining({
        notes: "Mara burns the bridge back to the archive.",
        open_questions: [
          "Who witnesses the break?",
          "What does it cost immediately?",
          "What can Mara no longer undo?",
        ],
      }),
    );
    expect(env.onPlotSaved).toHaveBeenCalledTimes(1);
  });

  it("refuses beat field updates when the target plot beat is missing", async () => {
    const env = harness({
      plot_main: makePlotNode("plot_main", {
        template_instance: {
          template_id: "three_act",
          plot_points: [{ plot_point_id: "setup_pressure", title: "Setup", function_claim: "", notes: "", metadata: {} }],
          metadata: {},
        },
      }),
    });

    await expect(
      env.actions.applyPlotSuggestionBeatFields({
        ...baseSuggestion,
        kind: "beat_revision",
        story_specifics: "A concrete story version.",
      }),
    ).rejects.toThrow("Could not find that plot beat on the target template instance.");
    expect(env.api.savePlotNode).not.toHaveBeenCalled();
  });
});
