import { describe, expect, it } from "vitest";
import {
  appendPlotSuggestionEvidence,
  appendPlotSuggestionText,
  canCreatePlotSuggestionBadge,
  parsePlotSuggestions,
  plotSuggestionClipboardText,
  stripPlotSuggestions,
} from "./plotSuggestions";

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

describe("appendPlotSuggestionEvidence", () => {
  it("appends new evidence without replacing existing claim evidence", () => {
    expect(appendPlotSuggestionEvidence("Existing support.", "Show the consequence.")).toBe(
      "Existing support.\n\nShow the consequence.",
    );
  });

  it("is idempotent when the evidence is already present", () => {
    expect(appendPlotSuggestionEvidence("Existing support.\n\nShow the consequence.", "Show the consequence.")).toBe(
      "Existing support.\n\nShow the consequence.",
    );
  });

  it("does not treat partial text matches as already applied", () => {
    expect(appendPlotSuggestionEvidence("Show the consequence clearly.", "Show the consequence.")).toBe(
      "Show the consequence clearly.\n\nShow the consequence.",
    );
  });
});

describe("appendPlotSuggestionText", () => {
  it("supports the same append behavior for non-evidence note fields", () => {
    expect(appendPlotSuggestionText("Existing note.", "Try a sharper consequence.")).toBe(
      "Existing note.\n\nTry a sharper consequence.",
    );
  });
});

describe("canCreatePlotSuggestionBadge", () => {
  it("accepts new-claim suggestions that identify a card and plot beat", () => {
    expect(canCreatePlotSuggestionBadge({
      kind: "new_claim",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Add lock-in badge",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
    })).toBe(true);
  });

  it("rejects suggestions that already target an existing claim", () => {
    expect(canCreatePlotSuggestionBadge({
      kind: "new_claim",
      target_card_id: "card_archive",
      target_claim_id: "claim_first_turn",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Add lock-in badge",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
    })).toBe(false);
  });
});
