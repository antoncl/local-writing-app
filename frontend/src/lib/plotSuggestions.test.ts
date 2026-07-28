import { describe, expect, it } from "vitest";
import {
  appendPlotSuggestionEvidence,
  appendPlotSuggestionText,
  canApplyPlotSuggestionBeatFields,
  canApplyPlotSuggestionCardSynopsis,
  canApplyPlotSuggestionClaimNote,
  canCreatePlotSuggestionCard,
  canCreatePlotSuggestionBadge,
  canCopyPlotSuggestionQuestion,
  parsePlotSuggestions,
  plotSuggestionBeatClipboardText,
  plotSuggestionClipboardText,
  plotSuggestionKindLabel,
  plotSuggestionQuestionClipboardText,
  plotSuggestionTargets,
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
        story_specifics: "",
        author_intent: "",
        expected_role: "",
        open_questions: [],
        status: "",
      },
    ]);
  });

  it("extracts plot beat field suggestions", () => {
    const suggestions = parsePlotSuggestions(`
<plot_suggestions>
  <suggestion kind="beat_revision" template_instance_id="plot_main" plot_point_id="first_turn">
    <title>Specify the lock-in</title>
    <reason>The generic beat needs this story's irreversible turn.</reason>
    <story_specifics>Mara burns her bridge back to the archive.</story_specifics>
    <author_intent>Commit her to theft over loyalty.</author_intent>
    <expected_role>Make retreat emotionally impossible.</expected_role>
    <open_question>Who witnesses the break?</open_question>
    <open_question>What does it cost immediately?</open_question>
    <status>planned</status>
  </suggestion>
</plot_suggestions>
`);

    expect(suggestions).toEqual([
      {
        kind: "beat_revision",
        target_card_id: "",
        target_claim_id: "",
        template_instance_id: "plot_main",
        plot_point_id: "first_turn",
        title: "Specify the lock-in",
        reason: "The generic beat needs this story's irreversible turn.",
        proposed_change: "",
        evidence_to_add: "",
        story_specifics: "Mara burns her bridge back to the archive.",
        author_intent: "Commit her to theft over loyalty.",
        expected_role: "Make retreat emotionally impossible.",
        open_questions: ["Who witnesses the break?", "What does it cost immediately?"],
        status: "planned",
      },
    ]);
  });

  it("extracts new card suggestions", () => {
    const suggestions = parsePlotSuggestions(`
<plot_suggestions>
  <suggestion kind="new_card" template_instance_id="plot_main" plot_point_id="first_turn">
    <title>Ledger theft</title>
    <reason>This gives the turn a concrete irreversible action.</reason>
    <proposed_change>Mara steals the ledger and loses her only way back.</proposed_change>
    <evidence_to_add>The archive doors lock behind her.</evidence_to_add>
  </suggestion>
</plot_suggestions>
`);

    expect(suggestions).toEqual([
      expect.objectContaining({
        kind: "new_card",
        target_card_id: "",
        target_claim_id: "",
        template_instance_id: "plot_main",
        plot_point_id: "first_turn",
        title: "Ledger theft",
        reason: "This gives the turn a concrete irreversible action.",
        proposed_change: "Mara steals the ledger and loses her only way back.",
        evidence_to_add: "The archive doors lock behind her.",
      }),
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
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    }, "proposed_change")).toBe([
      "Strengthen lock-in",
      "Proposed change: Add a consequence.",
      "Reason: Mara can still walk away too easily.",
      "Card: card_archive",
      "Story marker: claim_first_turn",
      "Template: plot_main",
      "Story beat: first_turn",
    ].join("\n"));
  });
});

describe("plotSuggestionBeatClipboardText", () => {
  it("formats suggested plot beat fields", () => {
    expect(plotSuggestionBeatClipboardText({
      kind: "beat_revision",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Specify the lock-in",
      reason: "The generic beat needs this story's irreversible turn.",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "Mara burns her bridge back to the archive.",
      author_intent: "Commit her to theft over loyalty.",
      expected_role: "Make retreat emotionally impossible.",
      open_questions: ["Who witnesses the break?"],
      status: "planned",
    })).toBe([
      "Specify the lock-in",
      "Story specifics: Mara burns her bridge back to the archive.",
      "Author intent: Commit her to theft over loyalty.",
      "Expected role: Make retreat emotionally impossible.",
      "Open question: Who witnesses the break?",
      "Status: planned",
      "Reason: The generic beat needs this story's irreversible turn.",
      "Template: plot_main",
      "Story beat: first_turn",
    ].join("\n"));
  });
});

describe("plotSuggestionQuestionClipboardText", () => {
  it("formats a decision prompt with target context", () => {
    expect(plotSuggestionQuestionClipboardText({
      kind: "question",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Choose the cost",
      reason: "The turn needs an immediate consequence.",
      proposed_change: "Decide who notices the theft first.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: ["Who witnesses Mara?", "What can she no longer undo?"],
      status: "",
    })).toBe([
      "Choose the cost",
      "Decision: Decide who notices the theft first.",
      "Question: Who witnesses Mara?",
      "Question: What can she no longer undo?",
      "Why it matters: The turn needs an immediate consequence.",
      "Card: card_archive",
      "Template: plot_main",
      "Beat: first_turn",
    ].join("\n"));
  });
});

describe("plotSuggestionTargets", () => {
  it("labels target ids before presenting them", () => {
    expect(plotSuggestionTargets({
      kind: "claim_change",
      target_card_id: "card_archive",
      target_claim_id: "claim_first_turn",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toEqual([
      { label: "Card", value: "card_archive" },
      { label: "Marker", value: "claim_first_turn" },
      { label: "Template", value: "plot_main" },
      { label: "Beat", value: "first_turn" },
    ]);
  });
});

describe("plotSuggestionKindLabel", () => {
  it("maps internal suggestion kinds to writer-facing labels", () => {
    expect(plotSuggestionKindLabel("claim_change")).toBe("Story marker change");
    expect(plotSuggestionKindLabel("new_claim")).toBe("New story marker");
    expect(plotSuggestionKindLabel("beat_revision")).toBe("Story beat change");
    expect(plotSuggestionKindLabel("unknown")).toBe("Suggestion");
  });
});

describe("canCopyPlotSuggestionQuestion", () => {
  it("only enables the dedicated copy action for concrete question suggestions", () => {
    expect(canCopyPlotSuggestionQuestion({
      kind: "question",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: ["What has to be decided?"],
      status: "",
    })).toBe(true);
    expect(canCopyPlotSuggestionQuestion({
      kind: "card_revision",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Change the card",
      reason: "",
      proposed_change: "A replacement synopsis.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
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
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
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
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });
});

describe("canApplyPlotSuggestionBeatFields", () => {
  it("accepts beat suggestions with a target and story-specific field", () => {
    expect(canApplyPlotSuggestionBeatFields({
      kind: "beat_revision",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Specify the beat",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "A concrete story version.",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(true);
  });
});

describe("canApplyPlotSuggestionCardSynopsis", () => {
  it("accepts card revision suggestions with a target card and proposed synopsis", () => {
    expect(canApplyPlotSuggestionCardSynopsis({
      kind: "card_revision",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Sharpen opening",
      reason: "",
      proposed_change: "Mara steals the ledger and loses her only way back.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(true);
  });

  it("rejects card revision suggestions without concrete replacement text", () => {
    expect(canApplyPlotSuggestionCardSynopsis({
      kind: "card_revision",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Sharpen opening",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });
});

describe("canApplyPlotSuggestionClaimNote", () => {
  it("accepts claim change suggestions with a target claim and proposed note", () => {
    expect(canApplyPlotSuggestionClaimNote({
      kind: "claim_change",
      target_card_id: "card_archive",
      target_claim_id: "claim_first_turn",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Strengthen lock-in",
      reason: "",
      proposed_change: "Make the consequence harder to evade.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(true);
  });

  it("rejects card revisions even when they mention a related claim", () => {
    expect(canApplyPlotSuggestionClaimNote({
      kind: "card_revision",
      target_card_id: "card_archive",
      target_claim_id: "claim_first_turn",
      template_instance_id: "plot_main",
      plot_point_id: "first_turn",
      title: "Sharpen opening",
      reason: "",
      proposed_change: "Mara steals the ledger and loses her only way back.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });
});

describe("canCreatePlotSuggestionCard", () => {
  it("accepts new card suggestions with a title and synopsis", () => {
    expect(canCreatePlotSuggestionCard({
      kind: "new_card",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Ledger theft",
      reason: "",
      proposed_change: "Mara steals the ledger and loses her only way back.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(true);
  });

  it("rejects new card suggestions without a concrete synopsis", () => {
    expect(canCreatePlotSuggestionCard({
      kind: "new_card",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Ledger theft",
      reason: "",
      proposed_change: "",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });

  it("rejects new card suggestions that still target an existing card", () => {
    expect(canCreatePlotSuggestionCard({
      kind: "new_card",
      target_card_id: "card_archive",
      target_claim_id: "",
      template_instance_id: "",
      plot_point_id: "",
      title: "Ledger theft",
      reason: "",
      proposed_change: "Mara steals the ledger.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });

  it("rejects new card suggestions with only one optional badge target id", () => {
    expect(canCreatePlotSuggestionCard({
      kind: "new_card",
      target_card_id: "",
      target_claim_id: "",
      template_instance_id: "plot_main",
      plot_point_id: "",
      title: "Ledger theft",
      reason: "",
      proposed_change: "Mara steals the ledger.",
      evidence_to_add: "",
      story_specifics: "",
      author_intent: "",
      expected_role: "",
      open_questions: [],
      status: "",
    })).toBe(false);
  });
});
