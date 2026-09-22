import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: { aiPreview: vi.fn() } }));
import { api } from "@/lib/api";
import { ChatEstimateController, type ChatEstimateDeps } from "./chatEstimate.svelte";
import type { PromptEntrySummary } from "@/lib/types";

const aiPreview = vi.mocked(api.aiPreview);

const entry = (body = "template body"): PromptEntrySummary =>
  ({ id: "p1", title: "P", body, inputs: [] }) as unknown as PromptEntrySummary;

function makeDeps(over: Partial<ChatEstimateDeps> = {}): ChatEstimateDeps {
  return {
    getPromptEntry: () => entry(),
    getInputs: () => ({}),
    getSubject: () => "",
    getAssistantId: () => "",
    mayCaptureLoreGate: () => true,
    setLoreEnabled: () => {},
    ...over,
  };
}

// A deferred promise, for the out-of-order-resolution test.
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe("ChatEstimateController (#2129)", () => {
  beforeEach(() => {
    aiPreview.mockReset();
  });

  it("no prompt entry: resets and fetches nothing", async () => {
    const controller = new ChatEstimateController(makeDeps({ getPromptEntry: () => null }));
    controller.estimate = { tokens: 1, cost_usd: null, cached: null, warnings: [], cache_blocks: [] };
    await controller.fetch();
    expect(aiPreview).not.toHaveBeenCalled();
    expect(controller.estimate).toBeNull();
    expect(controller.previewMessages).toBeNull();
    expect(controller.previewCacheBlocks).toEqual([]);
    expect(controller.previewLore).toBeNull();
  });

  it("a successful preview populates all four fields and maps cache_blocks to the summary shape", async () => {
    aiPreview.mockResolvedValue({
      messages: [{ role: "system", blocks: [{ text: "hi" }] }],
      warnings: ["a warning"],
      char_count: 0,
      rendered: true,
      estimated_tokens: 42,
      estimated_cost_usd: 0.01,
      cached: true,
      cache_blocks: [
        { label: "system", role: "system", tokens: 10, tier: "stable", cached: true, ttl_seconds: 3600, text: "full text", entry_ids: ["a"] },
      ],
      lore_fit: { budget_tokens: 100, used_tokens: 10, declared_tokens: 10, kept: 1, left_out: [] },
      lore_left_out_xml: { lore_1: "<xml/>" },
      lore_enabled: true,
    } as never);
    const deps = makeDeps();
    const controller = new ChatEstimateController(deps);
    await controller.fetch();
    expect(controller.estimate).toEqual({
      tokens: 42,
      cost_usd: 0.01,
      cached: true,
      warnings: ["a warning"],
      cache_blocks: [{ label: "system", tokens: 10, tier: "stable", cached: true, ttl_seconds: 3600 }],
    });
    expect(controller.previewMessages).toEqual([{ role: "system", blocks: [{ text: "hi" }] }]);
    expect(controller.previewCacheBlocks).toEqual([
      { label: "system", role: "system", tokens: 10, tier: "stable", cached: true, ttl_seconds: 3600, text: "full text", entry_ids: ["a"] },
    ]);
    expect(controller.previewLore).toEqual({
      fit: { budget_tokens: 100, used_tokens: 10, declared_tokens: 10, kept: 1, left_out: [] },
      leftOutXml: { lore_1: "<xml/>" },
    });
  });

  it("a preview.error resets", async () => {
    aiPreview.mockResolvedValue({
      messages: [],
      warnings: [],
      char_count: 0,
      rendered: false,
      error: { message: "boom", kind: "other" },
    } as never);
    const controller = new ChatEstimateController(makeDeps());
    controller.estimate = { tokens: 1, cost_usd: null, cached: null, warnings: [], cache_blocks: [] };
    await controller.fetch();
    expect(controller.estimate).toBeNull();
    expect(controller.previewMessages).toBeNull();
    expect(controller.previewCacheBlocks).toEqual([]);
    expect(controller.previewLore).toBeNull();
  });

  it("out-of-order guard: an earlier fetch resolving after a later one is dropped", async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    aiPreview.mockReturnValueOnce(first.promise as never);
    aiPreview.mockReturnValueOnce(second.promise as never);
    const controller = new ChatEstimateController(makeDeps());

    const fetchA = controller.fetch();
    const fetchB = controller.fetch();

    // B resolves first with tokens=2; A resolves after with tokens=1 — A must
    // be dropped, leaving B's result in place.
    second.resolve({ messages: [], warnings: [], char_count: 0, rendered: true, estimated_tokens: 2 });
    await fetchB;
    first.resolve({ messages: [], warnings: [], char_count: 0, rendered: true, estimated_tokens: 1 });
    await fetchA;

    expect(controller.estimate?.tokens).toBe(2);
  });

  it("the lore gate is written only when mayCaptureLoreGate() is true", async () => {
    aiPreview.mockResolvedValue({
      messages: [],
      warnings: [],
      char_count: 0,
      rendered: true,
      lore_enabled: true,
    } as never);
    const setLoreEnabled = vi.fn();
    const controller = new ChatEstimateController(
      makeDeps({ mayCaptureLoreGate: () => false, setLoreEnabled }),
    );
    await controller.fetch();
    expect(setLoreEnabled).not.toHaveBeenCalled();

    const setLoreEnabled2 = vi.fn();
    const controller2 = new ChatEstimateController(
      makeDeps({ mayCaptureLoreGate: () => true, setLoreEnabled: setLoreEnabled2 }),
    );
    await controller2.fetch();
    expect(setLoreEnabled2).toHaveBeenCalledWith(true);
  });

  it("a thrown request leaves the previous state untouched", async () => {
    aiPreview.mockRejectedValue(new Error("network down"));
    const controller = new ChatEstimateController(makeDeps());
    const priorEstimate = { tokens: 9, cost_usd: null, cached: null, warnings: [], cache_blocks: [] };
    controller.estimate = priorEstimate;
    await controller.fetch();
    expect(controller.estimate).toBe(priorEstimate);
  });
});
