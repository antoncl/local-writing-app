import { describe, expect, it } from "vitest";
import { cardAssistFocus } from "./plotBoardClaimAudit";
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
