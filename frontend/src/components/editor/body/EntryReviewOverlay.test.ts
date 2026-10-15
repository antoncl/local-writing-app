// @vitest-environment happy-dom
// #1797 round 2 (Y1): a failed accept-time step (a tag-vocabulary flip's
// title→id resolve/mint) sets `EntryProposalController.commitError`, and the
// overlay is where it must surface — above whichever review presentation is
// active, so the author sees why nothing saved.
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import EntryReviewOverlay from "./EntryReviewOverlay.svelte";
import { EntryProposalController } from "@/lib/stores/entryProposal.svelte";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
import type { MetadataSchema } from "@/lib/types";

const schema = {
  entry_types: {},
  fields: { allegiance: { name: "Allegiance", type: "select", options: [] } },
} as unknown as MetadataSchema;

function reviewWithProposal(): EntryProposalController {
  const review = new EntryProposalController();
  review.nodeId = "e1";
  review.schema = schema;
  entryBrainstorm.propose("e1", { body: null, fields: { allegiance: "Crown" } });
  return review;
}

beforeEach(() => {
  entryBrainstorm.clear("e1");
});

describe("EntryReviewOverlay — commitError banner (round 2, Y1)", () => {
  it("shows nothing when commitError is unset", () => {
    const review = reviewWithProposal();
    render(EntryReviewOverlay, { props: { review } });
    expect(screen.queryByText("network down")).toBeNull();
  });

  it("renders the message when commitError is set, above the review card", () => {
    const review = reviewWithProposal();
    review.commitError = "network down";
    render(EntryReviewOverlay, { props: { review } });
    expect(screen.getByText("network down")).toBeInTheDocument();
  });
});

describe("EntryReviewOverlay — Follow-ups section (ADR-0099 §4)", () => {
  const followUps = [
    { entry_id: "e2", entry_name: "Kaela Voss", change: "Make her older", why: "she saw the war" },
    { entry_id: "e3", entry_name: "Marek Vell", change: "Give him a scar", why: "" },
  ];

  it("renders nothing when the proposal has no follow-ups", () => {
    const review = reviewWithProposal();
    render(EntryReviewOverlay, { props: { review } });
    expect(screen.queryByTestId("follow-ups")).toBeNull();
  });

  it("renders one unticked row per follow-up, under the visual_diff review", () => {
    const review = reviewWithProposal();
    entryBrainstorm.propose("e1", { body: null, fields: { allegiance: "Crown" }, follow_ups: followUps });
    render(EntryReviewOverlay, { props: { review } });
    expect(screen.getByTestId("follow-ups")).toBeInTheDocument();
    expect(screen.getAllByTestId("follow-up-row")).toHaveLength(2);
    expect(screen.getByText("Kaela Voss")).toBeInTheDocument();
    expect(screen.getByText("she saw the war")).toBeInTheDocument();
    for (const tick of screen.getAllByTestId("follow-up-tick")) {
      expect((tick as HTMLInputElement).checked).toBe(false);
    }
  });

  it("also renders under the replace review, and ticking reaches the controller", async () => {
    const review = reviewWithProposal();
    entryBrainstorm.propose("e1", {
      body: null,
      fields: { allegiance: "Crown" },
      reviewMode: "replace",
      follow_ups: followUps,
    });
    render(EntryReviewOverlay, { props: { review } });
    await fireEvent.click(screen.getAllByTestId("follow-up-tick")[1]);
    expect(review.isFollowUpTicked(1)).toBe(true);
    expect(review.isFollowUpTicked(0)).toBe(false);
  });
});
