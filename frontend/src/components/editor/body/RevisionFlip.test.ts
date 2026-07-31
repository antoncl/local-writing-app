// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import { waitFor } from "@testing-library/svelte";

import RevisionFlip from "@/components/editor/body/RevisionFlip.svelte";

// The end-to-end guard for the #710 judge toggle: a view change must actually
// change the rendered prose. The controller owns the `view` state and the
// segmented control routes clicks, but the payoff lives here — RevisionFlip must
// pass `view` into `renderDiffRuns` so the overlay shows one whole version. A
// regression that ignored `view` (reverting to always-Both) would pass every
// state/routing test; only asserting on the rendered output catches it.

function renderFlip(view: "now" | "was" | "both") {
  return render(RevisionFlip, {
    props: {
      currentText: "the current wording",
      proposedText: "the proposed wording",
      label: "Body",
      view,
      onResolved: vi.fn(),
    },
  });
}

describe("RevisionFlip — view drives the rendered prose (#710)", () => {
  it("Current shows the current wording whole, not the proposed", async () => {
    const { container } = renderFlip("now");
    await waitFor(() => expect(container).toHaveTextContent("current wording"));
    expect(container).not.toHaveTextContent("proposed wording");
  });

  it("Proposed shows the proposed wording whole, not the current", async () => {
    const { container } = renderFlip("was");
    await waitFor(() => expect(container).toHaveTextContent("proposed wording"));
    expect(container).not.toHaveTextContent("current wording");
  });

  it("Both shows both versions interleaved", async () => {
    // The modification renders the two wordings adjacent (cool `proposed`, warm
    // `current`), so assert both words are present rather than either whole.
    const { container } = renderFlip("both");
    await waitFor(() => expect(container).toHaveTextContent("proposed"));
    expect(container).toHaveTextContent("current");
  });

  it("renders the label", () => {
    renderFlip("both");
    expect(screen.getByText("Body")).toBeInTheDocument();
  });
});
