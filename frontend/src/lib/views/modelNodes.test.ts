import { describe, it, expect } from "vitest";
import type { AIModelInfo } from "@/lib/types";
import { evaluateView } from "@/lib/views/evaluateView";
import {
  MODEL_ENTRY_TYPE,
  MODEL_FREE_FIELD,
  modelInfoToEvalNodes,
  modelPickerView,
} from "@/lib/views/modelNodes";

function model(partial: Partial<AIModelInfo> & { id: string }): AIModelInfo {
  return {
    display_name: partial.id,
    provider: "openrouter",
    context_window: 128000,
    tier: "balanced",
    capabilities: [],
    deprecated: false,
    cost_in_per_mtok: 1,
    family: "",
    free: false,
    ...partial,
  };
}

describe("modelInfoToEvalNodes", () => {
  it("lifts a model to an EvalNode with facets in metadata", () => {
    const [node] = modelInfoToEvalNodes([
      model({ id: "qwen/qwen-2.5-72b", display_name: "Qwen 2.5 72B", family: "qwen", free: true }),
    ]);
    expect(node.id).toBe("qwen/qwen-2.5-72b");
    expect(node.entry_type).toBe(MODEL_ENTRY_TYPE);
    // title is what the row renders — the model's display name, not its id.
    expect(node.title).toBe("Qwen 2.5 72B");
    expect(node.metadata.family).toBe("qwen");
    expect(node.metadata[MODEL_FREE_FIELD]).toBe(true);
    expect(node.metadata.tier).toBe("balanced");
    expect(node.metadata.context).toBe(128000);
  });
});

describe("modelPickerView over the lifted roster", () => {
  const models = [
    model({ id: "anthropic/claude-3.5-sonnet", family: "anthropic" }),
    model({ id: "anthropic/claude-3-haiku", family: "anthropic", tier: "fast" }),
    model({ id: "qwen/qwen-2.5-72b", family: "qwen", free: true, cost_in_per_mtok: 0 }),
    model({ id: "openai/gpt-4o", family: "openai", tier: "premium" }),
  ];

  it("matches the whole roster with no schema (the seed-inclusive ai_model:base root)", () => {
    // The critical correctness check: the fixed view resolves `ai_model:base`
    // schema-lessly, so every lifted model must survive the roster — a missed
    // root match would render an empty picker.
    const result = evaluateView(modelPickerView(), modelInfoToEvalNodes(models));
    expect(result.nodes.map((n) => n.id).sort()).toEqual(models.map((m) => m.id).sort());
  });

  it("groups by family (alphabetical labels)", () => {
    const result = evaluateView(modelPickerView(), modelInfoToEvalNodes(models));
    expect(result.groups).not.toBeNull();
    expect(result.groups!.map((g) => g.label)).toEqual(["anthropic", "openai", "qwen"]);
  });
});
