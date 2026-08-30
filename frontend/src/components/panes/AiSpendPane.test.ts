// @vitest-environment happy-dom
// AI Spend pane render contract (#10, per the #642 rule: a pane that displays
// data needs a mount test asserting rows actually reach the DOM). Also pins
// the honesty rule: an all-unpriced scope shows "—", never €0.00 (#697).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import AiSpendPane from "./AiSpendPane.svelte";
import { api } from "@/lib/api";
import { aiSpend } from "@/lib/stores/aiSpend.svelte";
import type { AICostBucket, AICostSummary } from "@/lib/types";

vi.mock("@/lib/api", () => ({ api: { aiCostSummary: vi.fn() } }));

function bucket(partial: Partial<AICostBucket>): AICostBucket {
  return {
    key: "k",
    label: "k",
    cost_usd: null,
    count: 0,
    unpriced_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    ...partial,
  };
}

function summary(partial: Partial<AICostSummary>): AICostSummary {
  return {
    total_cost_usd: 0,
    count: 0,
    unpriced_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    by_model: [],
    by_chat: [],
    by_scene: [],
    by_prompt: [],
    by_day: [],
    ...partial,
  };
}

beforeEach(() => {
  vi.mocked(api.aiCostSummary).mockReset();
  // The store is a module singleton — clear state a prior test left behind.
  aiSpend.summary = null;
  aiSpend.error = "";
  aiSpend.range = "all";
});

describe("AI Spend pane — rollup renders", () => {
  it("renders the headline total and breakdown rows", async () => {
    vi.mocked(api.aiCostSummary).mockResolvedValue(
      summary({
        total_cost_usd: 10.0,
        count: 3,
        input_tokens: 12_000,
        output_tokens: 3_400,
        by_model: [
          bucket({ key: "claude-opus-5", label: "claude-opus-5", cost_usd: 8.0, count: 2 }),
          bucket({ key: "claude-haiku-4-5", label: "claude-haiku-4-5", cost_usd: 2.0, count: 1 }),
        ],
        by_chat: [bucket({ key: "chat_1", label: "Plot brainstorm", cost_usd: 8.0, count: 2 })],
        by_day: [bucket({ key: "2026-08-30", label: "2026-08-30", cost_usd: 10.0, count: 3 })],
      }),
    );
    render(AiSpendPane, { props: { projectKey: "/tmp/p" } });
    await tick();
    await tick();

    expect(api.aiCostSummary).toHaveBeenCalledWith({ since: undefined });
    // 10 USD at the fixed 0.92 rate — the display is EUR everywhere.
    expect(screen.getByTestId("ai-spend-total").textContent).toContain("€9.20");
    expect(screen.getByText("claude-opus-5")).toBeInTheDocument();
    expect(screen.getByText("claude-haiku-4-5")).toBeInTheDocument();
    expect(screen.getByText("Plot brainstorm")).toBeInTheDocument();
    expect(screen.getByText("2026-08-30")).toBeInTheDocument();
    // A section with no buckets doesn't render an empty shell.
    expect(screen.queryByTestId("ai-spend-by-scene")).not.toBeInTheDocument();
  });

  it("shows — (not €0.00) when every row in scope is unpriced", async () => {
    // The server ships null for an all-unpriced scope (#697); the pane must
    // render it as — with the unpriced note, never as a confident €0.00.
    vi.mocked(api.aiCostSummary).mockResolvedValue(
      summary({
        total_cost_usd: null,
        count: 2,
        unpriced_count: 2,
        by_model: [
          bucket({ key: "llama3", label: "llama3", cost_usd: null, count: 2, unpriced_count: 2 }),
        ],
      }),
    );
    render(AiSpendPane, { props: { projectKey: "/tmp/p" } });
    await tick();
    await tick();

    expect(screen.getByTestId("ai-spend-total").textContent?.trim()).toBe("—");
    const modelRows = screen.getByTestId("ai-spend-by-model");
    expect(modelRows.textContent).toContain("llama3");
    expect(modelRows.textContent).toContain("2 unpriced");
    expect(modelRows.textContent).not.toContain("€0.00");
  });

  it("keeps the last-good summary when a refresh fails", async () => {
    vi.mocked(api.aiCostSummary).mockResolvedValue(
      summary({ total_cost_usd: 10.0, count: 3 }),
    );
    render(AiSpendPane, { props: { projectKey: "/tmp/p" } });
    await tick();
    await tick();
    expect(screen.getByTestId("ai-spend-total").textContent).toContain("€9.20");

    vi.mocked(api.aiCostSummary).mockRejectedValue(new Error("backend gone"));
    await fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await tick();
    await tick();

    // The stats stay on screen; the error renders alongside, not instead.
    expect(screen.getByTestId("ai-spend-total").textContent).toContain("€9.20");
    expect(screen.getByText(/Couldn't load AI spend/)).toBeInTheDocument();
  });

  it("refetches with a since-bound when a range is picked", async () => {
    vi.mocked(api.aiCostSummary).mockResolvedValue(summary({}));
    render(AiSpendPane, { props: { projectKey: "/tmp/p" } });
    await tick();

    await fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    await tick();

    const lastCall = vi.mocked(api.aiCostSummary).mock.calls.at(-1)?.[0];
    expect(lastCall?.since).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
