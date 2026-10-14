// @vitest-environment happy-dom
// LineNoteReviewBar (ADR-0098): the review bar for a lore check's pending notes.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import LineNoteReviewBar from "./LineNoteReviewBar.svelte";

const CHECKED = [
  { id: "lore_1", name: "Mira" },
  { id: "lore_2", name: "The Keep" },
  { id: "lore_3", name: "" },
];

function mount(
  lineNotes: { remaining: number; index: number; checkedAgainst: typeof CHECKED } | null = {
    remaining: 3,
    index: 2,
    checkedAgainst: CHECKED,
  },
  generating = false,
) {
  const fns = { onDismissAll: vi.fn(), onRetry: vi.fn() };
  const meta = { provider: "p", model: "claude-x", latency_ms: 1, truncated: false, wordCount: 3, usage: null, cost_usd: 0.5 };
  const utils = render(LineNoteReviewBar, { props: { lineNotes, meta, generating, ...fns } as never });
  return { ...utils, fns };
}

describe("LineNoteReviewBar", () => {
  it("renders nothing when no notes are pending", () => {
    mount(null);
    expect(screen.queryByTestId("line-note-review-bar")).toBeNull();
  });

  it("shows Note N of M, the model and the checked-against names (full list as the title)", () => {
    mount();
    expect(screen.getByTestId("line-note-count").textContent).toBe("Note 2 of 3");
    expect(screen.getByTestId("line-note-meta").textContent).toContain("claude-x");
    const checked = screen.getByTestId("line-note-checked");
    expect(checked.textContent).toBe("Checked against: Mira, The Keep, lore_3");
    expect(checked.getAttribute("title")).toBe("Mira, The Keep, lore_3");
  });

  it("omits the checked-against line when the check ran against nothing", () => {
    mount({ remaining: 1, index: 1, checkedAgainst: [] });
    expect(screen.queryByTestId("line-note-checked")).toBeNull();
  });

  it("has no accept control: a note is dismissed, never accepted", () => {
    mount();
    expect(screen.queryByTestId("line-edit-accept-all")).toBeNull();
    expect(screen.queryByTestId("line-note-accept-all")).toBeNull();
  });

  it("Dismiss all and Retry call through; Retry is disabled while generating", async () => {
    const { fns } = mount();
    await fireEvent.click(screen.getByTestId("line-note-dismiss-all"));
    expect(fns.onDismissAll).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByTestId("line-note-retry"));
    expect(fns.onRetry).toHaveBeenCalledTimes(1);
  });

  it("disables Retry while generating", () => {
    mount(undefined, true);
    expect((screen.getByTestId("line-note-retry") as HTMLButtonElement).disabled).toBe(true);
  });
});
