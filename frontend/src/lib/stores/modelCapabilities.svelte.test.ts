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

  it("treats a failed fetch as unknown without throwing, and doesn't hammer it from ensure()", async () => {
    vi.useFakeTimers();
    try {
      listAIProviderModels.mockRejectedValue(new Error("offline"));
      await expect(modelCapabilities.ensure(["ollama"])).resolves.toBeUndefined();
      expect(modelCapabilities.supportsTools("ollama", "x")).toBeNull();
      // A re-render's ensure() during the retry run doesn't add a request.
      await modelCapabilities.ensure(["ollama"]);
      expect(listAIProviderModels).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries a provider that wasn't up yet, then gives up after the backoff run", async () => {
    vi.useFakeTimers();
    try {
      listAIProviderModels.mockRejectedValue(new Error("not up yet"));
      await modelCapabilities.ensure(["ollama"]);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(listAIProviderModels).toHaveBeenCalledTimes(2);
      // Ollama comes up: the next scheduled retry loads it.
      listAIProviderModels.mockResolvedValue({ models: [model("qwen", ["tools"])] });
      await vi.advanceTimersByTimeAsync(60_000);
      expect(listAIProviderModels).toHaveBeenCalledTimes(3);
      expect(modelCapabilities.supportsTools("ollama", "qwen")).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops retrying after the backoff run", async () => {
    vi.useFakeTimers();
    try {
      listAIProviderModels.mockRejectedValue(new Error("absent"));
      await modelCapabilities.ensure(["ollama"]);
      await vi.advanceTimersByTimeAsync(30_000 + 60_000 + 120_000 + 600_000);
      expect(listAIProviderModels).toHaveBeenCalledTimes(4); // first try + 3 retries
    } finally {
      vi.useRealTimers();
    }
  });

  it("prime() fills the catalogue the picker already fetched, ending a retry run", async () => {
    vi.useFakeTimers();
    try {
      listAIProviderModels.mockRejectedValue(new Error("not up yet"));
      await modelCapabilities.ensure(["ollama"]);
      modelCapabilities.prime("ollama", [model("qwen", ["tools"]), model("llama", [])]);
      expect(modelCapabilities.supportsTools("ollama", "qwen")).toBe(true);
      expect(modelCapabilities.supportsTools("ollama", "llama")).toBe(false);
      await vi.advanceTimersByTimeAsync(600_000);
      expect(listAIProviderModels).toHaveBeenCalledTimes(1); // the pending retry was cancelled
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores an empty provider", async () => {
    await modelCapabilities.ensure([""]);
    expect(listAIProviderModels).not.toHaveBeenCalled();
  });
});
