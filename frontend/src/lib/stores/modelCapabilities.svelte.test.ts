import { beforeEach, describe, expect, it, vi } from "vitest";

const listAIProviderModels = vi.fn();
vi.mock("@/lib/api", () => ({ api: { listAIProviderModels: (p: string) => listAIProviderModels(p) } }));

import { modelCapabilities } from "./modelCapabilities.svelte";

const model = (id: string, capabilities: string[]) => ({ id, capabilities });

beforeEach(() => {
  modelCapabilities.reset();
  listAIProviderModels.mockReset();
});

describe("modelCapabilities (#2485)", () => {
  it("answers true / false for known models and null for unknown ones", async () => {
    listAIProviderModels.mockResolvedValue({ models: [model("a", ["tools", "vision"]), model("b", [])] });
    await modelCapabilities.ensure(["anthropic"]);
    expect(modelCapabilities.supportsTools("anthropic", "a")).toBe(true);
    expect(modelCapabilities.supportsTools("anthropic", "b")).toBe(false);
    expect(modelCapabilities.supportsTools("anthropic", "missing")).toBeNull();
    expect(modelCapabilities.supportsTools("openai", "a")).toBeNull();
  });

  it("dedupes concurrent requests and caches per provider", async () => {
    listAIProviderModels.mockResolvedValue({ models: [model("a", ["tools"])] });
    await Promise.all([modelCapabilities.ensure(["anthropic"]), modelCapabilities.ensure(["anthropic", "openai"])]);
    await modelCapabilities.ensure(["anthropic", "openai"]);
    expect(listAIProviderModels).toHaveBeenCalledTimes(2);
    expect(listAIProviderModels.mock.calls.map((c) => c[0]).sort()).toEqual(["anthropic", "openai"]);
  });

  it("treats a failed fetch as unknown, without throwing or retrying", async () => {
    listAIProviderModels.mockRejectedValue(new Error("offline"));
    await expect(modelCapabilities.ensure(["ollama"])).resolves.toBeUndefined();
    expect(modelCapabilities.supportsTools("ollama", "x")).toBeNull();
    await modelCapabilities.ensure(["ollama"]);
    expect(listAIProviderModels).toHaveBeenCalledTimes(1);
  });

  it("ignores an empty provider", async () => {
    await modelCapabilities.ensure([""]);
    expect(listAIProviderModels).not.toHaveBeenCalled();
  });
});
