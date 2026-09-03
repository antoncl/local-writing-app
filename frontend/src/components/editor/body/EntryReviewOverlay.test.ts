// @vitest-environment happy-dom
// #1797 round 2 (Y1): a failed accept-time step (a tag-vocabulary flip's
// title→id resolve/mint) sets `EntryProposalController.commitError`, and the
// overlay is where it must surface — above whichever review presentation is
// active, so the author sees why nothing saved.
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
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
