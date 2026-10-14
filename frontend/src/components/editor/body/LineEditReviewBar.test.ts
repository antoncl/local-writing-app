// @vitest-environment happy-dom
// LineEditReviewBar (#2460): the bottom review bar for a Line edit's pending edits.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import LineEditReviewBar from "./LineEditReviewBar.svelte";

const REASON = "A livelier verb that keeps the rhythm of the sentence and then some more words";

function mount(lineEdits: { remaining: number; index: number; currentReason: string } | null = { remaining: 3, index: 2, currentReason: REASON }) {
  const fns = {
    onPrev: vi.fn(),
    onNext: vi.fn(),
    onAccept: vi.fn(),
    onReject: vi.fn(),
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

  it("shows Edit N of M, the current reason (full text in title) and the model", () => {
    mount();
    expect(screen.getByTestId("line-edit-count").textContent).toBe("Edit 2 of 3");
    const reason = screen.getByTestId("line-edit-reason");
    expect(reason.textContent).toBe(REASON);
    expect(reason.getAttribute("title")).toBe(REASON);
    expect(screen.getByTestId("line-edit-meta").textContent).toContain("claude-x");
  });

  it("every control calls through, and names its shortcut where there is one", async () => {
    const { fns } = mount();
    const wiring: [string, keyof typeof fns][] = [
      ["line-edit-prev", "onPrev"],
      ["line-edit-next", "onNext"],
      ["line-edit-accept", "onAccept"],
      ["line-edit-reject", "onReject"],
      ["line-edit-accept-all", "onAcceptAll"],
      ["line-edit-reject-all", "onRejectAll"],
      ["line-edit-retry", "onRetry"],
    ];
    for (const [testid, fn] of wiring) {
      await fireEvent.click(screen.getByTestId(testid));
      expect(fns[fn]).toHaveBeenCalledTimes(1);
    }
    expect(screen.getByTestId("line-edit-accept").getAttribute("title")).toContain("Alt+Enter");
    expect(screen.getByTestId("line-edit-next").getAttribute("aria-label")).toBe("Next edit");
  });
});
