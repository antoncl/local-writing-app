import { describe, expect, it } from "vitest";
import { parsePlotSuggestions, plotSuggestionClipboardText, stripPlotSuggestions } from "./plotSuggestions";

describe("parsePlotSuggestions", () => {
  it("extracts concrete suggestions with target ids", () => {
    const suggestions = parsePlotSuggestions(`
Intro text.
<plot_suggestions>
  <suggestion kind="claim_change" target_card_id="card_archive" target_claim_id="claim_first_turn" template_instance_id="plot_main" plot_point_id="first_turn">
    <title>Strengthen lock-in</title>
    <reason>Mara can still walk away too easily.</reason>
    <proposed_change>Add a consequence that makes returning the ledger dangerous.</proposed_change>
    <evidence_to_add>Show who would expose her if she tries to undo the theft.</evidence_to_add>
  </suggestion>
</plot_suggestions>
`);

    expect(suggestions).toEqual([
      {
        kind: "claim_change",
        target_card_id: "card_archive",
        target_claim_id: "claim_first_turn",
        template_instance_id: "plot_main",
        plot_point_id: "first_turn",
        title: "Strengthen lock-in",
        reason: "Mara can still walk away too easily.",
        proposed_change: "Add a consequence that makes returning the ledger dangerous.",
        evidence_to_add: "Show who would expose her if she tries to undo the theft.",
      },
    ]);
  });

  it("ignores schema placeholders", () => {
    const suggestions = parsePlotSuggestions(`
<plot_suggestions>
  <suggestion kind="card_revision" target_card_id="card_id_if_known">
    <title>Short label for a real suggestion</title>
    <reason>Why this concrete change would strengthen the story function.</reason>
    <proposed_change>Specific board-level edit or author decision, not drafted prose.</proposed_change>
    <evidence_to_add>Concrete evidence the card or linked scene would need.</evidence_to_add>
  </suggestion>
</plot_suggestions>
`);

    expect(suggestions).toEqual([]);
  });
});

describe("stripPlotSuggestions", () => {
  it("removes suggestion blocks from rendered chat prose", () => {
    expect(stripPlotSuggestions("Before\n<plot_suggestions><suggestion></suggestion></plot_suggestions>\nAfter")).toBe("Before\n\nAfter");
  });
});

describe("plotSuggestionClipboardText", () => {
  it("formats a focused copy payload with useful target ids", () => {
    expect(plotSuggestionClipboardText({
      kind: "claim_change",
      target_card_id: "card_archive",
      target_claim_id: "claim_first_turn",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Strengthen lock-in",
      reason: "Mara can still walk away too easily.",
      proposed_change: "Add a consequence.",
      evidence_to_add: "Show who would expose her.",
    }, "proposed_change")).toBe([
      "Strengthen lock-in",
      "Proposed change: Add a consequence.",
      "Reason: Mara can still walk away too easily.",
      "Card: card_archive",
      "Claim: claim_first_turn",
      "Template instance: plot_main",
      "Plot beat: first_turn",
    ].join("\n"));
  });
});
