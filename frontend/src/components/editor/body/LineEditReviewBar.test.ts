// @vitest-environment happy-dom
// LineEditReviewBar (#2460): the review bar (a pane footer row) for a Line edit's pending edits.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import LineEditReviewBar from "./LineEditReviewBar.svelte";

function mount(lineEdits: { remaining: number; index: number } | null = { remaining: 3, index: 2 }) {
  const fns = {
    onAcceptAll: vi.fn(),
    onRejectAll: vi.fn(),
    onRetry: vi.fn(),
  };
  const meta = { provider: "p", model: "claude-x", latency_ms: 1, truncated: false, wordCount: 3, usage: null, cost_usd: 0.5 };
  const utils = render(LineEditReviewBar, { props: { lineEdits, meta, ...fns } as never });
  return { ...utils, fns };
}

describe("LineEditReviewBar", () => {
  it("renders nothing when no edits are pending", () => {
    mount(null);
    expect(screen.queryByTestId("line-edit-review-bar")).toBeNull();
  });

  it("shows Edit N of M and the model, but no per-edit controls or reason (those are the margin card)", () => {
    mount();
    expect(screen.getByTestId("line-edit-count").textContent).toBe("Edit 2 of 3");
    expect(screen.getByTestId("line-edit-meta").textContent).toContain("claude-x");
    for (const gone of ["line-edit-prev", "line-edit-next", "line-edit-accept", "line-edit-reject", "line-edit-reason"]) {
      expect(screen.queryByTestId(gone)).toBeNull();
    }
  });

  it("groups its controls so a narrow pane wraps whole groups onto a second row", () => {
    mount();
    const bar = screen.getByTestId("line-edit-review-bar");
    const groups = [...bar.querySelectorAll(".ler-group")].map((g) => [...g.querySelectorAll("button, .ler-count")].map((n) => n.getAttribute("data-testid")));
    expect(groups).toEqual([
      ["line-edit-count"],
      ["line-edit-accept-all", "line-edit-reject-all", "line-edit-retry"],
    ]);
  });

  it("every control calls through", async () => {
    const { fns } = mount();
    const wiring: [string, keyof typeof fns][] = [
      ["line-edit-accept-all", "onAcceptAll"],
      ["line-edit-reject-all", "onRejectAll"],
      ["line-edit-retry", "onRetry"],
    ];
    for (const [testid, fn] of wiring) {
      await fireEvent.click(screen.getByTestId(testid));
      expect(fns[fn]).toHaveBeenCalledTimes(1);
    }
  });
});
