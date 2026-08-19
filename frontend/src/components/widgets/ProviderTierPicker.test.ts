// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// The picker calls api.listAIProviders() on mount and api.listAIProviderModels()
// whenever the provider changes. Stub both so the test never reaches a real
// backend (#973 network guard), and give each provider a DIFFERENT balanced
// model so a switch can prove the picker resolves against the NEW provider's
// catalogue (see the fresh-read test below).
vi.mock("@/lib/api", () => {
  const modelsByProvider: Record<string, unknown[]> = {
    anthropic: [
      {
        id: "claude-bal",
        display_name: "Claude Balanced",
        provider: "anthropic",
        context_window: 200000,
        tier: "balanced",
        capabilities: [],
        deprecated: false,
        cost_in_per_mtok: 3,
      },
    ],
    openai: [
      {
        id: "gpt-bal",
        display_name: "GPT Balanced",
        provider: "openai",
        context_window: 128000,
        tier: "balanced",
        capabilities: [],
        deprecated: false,
        cost_in_per_mtok: 2,
      },
    ],
  };
  return {
    api: {
      listAIProviders: vi.fn(async () => ({
        providers: [
          { name: "anthropic", display_name: "Anthropic" },
          { name: "openai", display_name: "OpenAI" },
        ],
      })),
      listAIProviderModels: vi.fn(async (provider: string) => ({
        models: modelsByProvider[provider] ?? [],
      })),
    },
  };
});

import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";

describe("ProviderTierPicker — onChange callback (runes port of the `change` event)", () => {
  it("defaults to the first provider on mount and reports it through onChange", async () => {
    const onChange = vi.fn();
    render(ProviderTierPicker, { props: { onChange } });

    // onMount picks the first provider when the entry is fresh and emits it.
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "anthropic", tier: "", model: "" }),
      ),
    );
  });

  it("resolves the tier against the NEWLY selected provider's catalogue, not the old one", async () => {
    // This locks the runes pull-semantics: onProviderChange reads the derived
    // tier resolutions synchronously after `await loadModels()`, so they must
    // reflect the just-loaded provider. Under the old push-batched `$:` these
    // reads were stale and would have resolved to the previous provider's model
    // ("claude-bal"); the correct result is the new provider's "gpt-bal".
    const onChange = vi.fn();
    render(ProviderTierPicker, { props: { onChange } });
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "anthropic" }),
      ),
    );

    const subscription = screen.getByLabelText("Subscription") as HTMLSelectElement;
    await fireEvent.change(subscription, { target: { value: "openai" } });

    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        provider: "openai",
        tier: "balanced",
        model: "gpt-bal",
      }),
    );
  });
});
