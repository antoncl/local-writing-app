// @vitest-environment happy-dom
// The `replace`-mode review card (ADR-0051 S5-next). The #642 lesson: a pane
// that must DISPLAY data needs a mount test asserting it renders — here, that
// the proposed value actually shows (not just that a callback wires up), and
// that Replace / Discard fire their gestures.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReplaceReviewCard from "./ReplaceReviewCard.svelte";
import type { FieldFlip } from "@/lib/utils/entryRevision";

const fields: FieldFlip[] = [
  {
    fieldId: "summary",
    label: "Summary",
    currentValue: "Old synopsis.",
    proposedValue: "A new synopsis of the scene.",
  },
];

describe("ReplaceReviewCard (ADR-0051 S5-next)", () => {
  it("renders both the current and the proposed value", () => {
    render(ReplaceReviewCard, {
      props: { fields, onReplace: () => {}, onDiscard: () => {} },
    });
    expect(screen.getByText("Old synopsis.")).toBeInTheDocument();
    expect(screen.getByText("A new synopsis of the scene.")).toBeInTheDocument();
  });

  it("Replace fires the commit gesture and Discard drops it", async () => {
    const onReplace = vi.fn();
    const onDiscard = vi.fn();
    render(ReplaceReviewCard, { props: { fields, onReplace, onDiscard } });

    await fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    expect(onReplace).toHaveBeenCalledOnce();
    expect(onDiscard).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it("shows an empty proposal as a placeholder, not a blank", () => {
    // A model that returns an empty summary must not render as an invisible box.
    render(ReplaceReviewCard, {
      props: {
        fields: [{ fieldId: "summary", label: "Summary", currentValue: "x", proposedValue: "" }],
        onReplace: () => {},
        onDiscard: () => {},
      },
    });
    expect(screen.getByText("(empty)")).toBeInTheDocument();
  });
});
