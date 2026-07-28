import { describe, expect, it } from "vitest";
import { beatAssistFocus, boardIdeationFocus, cardAssistFocus } from "./plotBoardClaimAudit";
import { buildPlotDiagnostics } from "./plotBoardDiagnostics";
import type { PlotBoardCard, PlotNode, PlotPointClaim } from "@/lib/types";

const card = {
  id: "card_opening",
  title: "Opening",
  synopsis: "Mara decides to steal the ledger.",
} as PlotBoardCard;

const weakClaim = {
  id: "claim_setup",
  card_id: card.id,
  template_instance_id: "template",
  plot_point_id: "setup_pressure",
  claim_type: "satisfies",
  strength: "weak",
  rationale: "",
  evidence: "",
  metadata: {},
} as PlotPointClaim;

describe("cardAssistFocus", () => {
  it("asks for concrete repair options for the selected card", () => {
    const plotNode = {
      id: "plot",
      title: "Book plot board",
      entry_type: "plot:board",
      board: {
        cards: [card],
        claims: [weakClaim],
      },
    } as PlotNode;
    const diagnostics = buildPlotDiagnostics([card], [weakClaim], [
      {
        instance: { id: "template" },
        point: { plot_point_id: "setup_pressure" },
        claims: [weakClaim],
      },
    ]);

    const focus = cardAssistFocus({
      plotNode,
      selectedCard: card,
      selectedClaim: null,
      selectedPaletteRow: null,
      selectedPointLabel: "",
      cardById: () => card,
      diagnostics,
    });

    expect(focus).toContain('Help make card "Opening" (id: card_opening) stronger');
    expect(focus).toContain("No rationale or evidence");
    expect(focus).toContain("Marked weak");
    expect(focus).toContain("[claim_setup]");
    expect(focus).toContain("Mara decides to steal the ledger.");
    expect(focus).toContain("narrative actions");
    expect(focus).toContain("draft suggestions with target ids");
    expect(focus).toContain("Do not draft prose");
    expect(focus).toContain("later apply manually");
  });
});

describe("boardIdeationFocus", () => {
  it("asks for practical structure options without adding terminology", () => {
    const plotNode = {
      id: "plot",
      title: "Book plot board",
      entry_type: "plot:board",
      board: {
        cards: [card],
        claims: [weakClaim],
      },
    } as PlotNode;
    const diagnostics = buildPlotDiagnostics([card], [weakClaim], [
      {
        instance: { id: "template" },
        point: { plot_point_id: "setup_pressure" },
        claims: [weakClaim],
      },
      {
        instance: { id: "template" },
        point: { plot_point_id: "missing" },
        claims: [],
      },
    ]);

    const focus = boardIdeationFocus({
      plotNode,
      selectedCard: null,
      selectedClaim: null,
      selectedPaletteRow: null,
      selectedPointLabel: "",
      cardById: () => null,
      diagnostics,
    });

    expect(focus).toContain('Brainstorm ways to simplify and strengthen "Book plot board"');
    expect(focus).toContain("1 card, 1 story marker");
    expect(focus).toContain("cards to add, split, merge, move, or clarify");
    expect(focus).toContain("Favor practical next steps over terminology or critique");
  });
});

describe("beatAssistFocus", () => {
  it("asks for concrete ways to make the selected plot beat feel earned", () => {
    const partialClaim = {
      ...weakClaim,
      claim_type: "partially_satisfies",
    } as PlotPointClaim;
    const plotNode = {
      id: "plot",
      title: "Book plot board",
      entry_type: "plot:board",
      board: {
        cards: [card],
        claims: [partialClaim],
      },
    } as PlotNode;
    const selectedPaletteRow = {
      instance: { id: "template", title: "Main plot" } as PlotNode,
      point: {
        plot_point_id: "setup_pressure",
        title: "Setup pressure",
        function_claim: "Establishes ordinary pressure before commitment.",
        notes: "Mara wants safety but is already compromised.",
        author_intent: "Make the theft feel like a reluctant choice.",
        metadata: {},
      },
      status: "partial" as const,
      claims: [partialClaim],
    };
    const diagnostics = buildPlotDiagnostics([card], [partialClaim], [selectedPaletteRow]);

    const focus = beatAssistFocus({
      plotNode,
      selectedCard: null,
      selectedClaim: null,
      selectedPaletteRow,
      selectedPointLabel: "",
      cardById: () => card,
      diagnostics,
    });

    expect(focus).toContain('make the plot beat "Setup pressure" feel earned');
    expect(focus).toContain('Template instance: "Main plot" (id: template)');
    expect(focus).toContain("Plot beat id: setup_pressure");
    expect(focus).toContain("Establishes ordinary pressure before commitment.");
    expect(focus).toContain("Mara wants safety but is already compromised.");
    expect(focus).toContain("Current board use: partial");
    expect(focus).toContain('[claim_setup] on "Opening"');
    expect(focus).toContain("No card clearly earns this");
    expect(focus).toContain("existing cards that could support this beat");
    expect(focus).toContain("possible new card");
    expect(focus).toContain("draft suggestions with target ids");
  });
});
