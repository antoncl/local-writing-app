// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// The picker calls api.getMachineSettings() on mount (ADR-0073 S2 — scoped by
// policy + credentials, not the flat provider list) and
// api.listAIProviderModels() whenever the provider changes. Stub both so the
// test never reaches a real backend (#973 network guard), and give each
// provider a DIFFERENT balanced model so a switch can prove the picker
// resolves against the NEW provider's catalogue (see the fresh-read test
// below). Both cloud keys are set so a "cloud-allowed" policy makes both
// eligible.
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
        family: "claude",
        free: false,
        verified: true,
      },
      {
        // Live-only, no baked audit entry (ADR-0073 S4) — pricier than
        // claude-bal so the balanced tier still resolves to claude-bal.
        id: "claude-unlisted",
        display_name: "Claude Unlisted",
        provider: "anthropic",
        context_window: 200000,
        tier: "balanced",
        capabilities: [],
        deprecated: false,
        cost_in_per_mtok: 10,
        family: "claude",
        free: false,
        verified: false,
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
        family: "gpt",
        free: false,
        verified: true,
      },
    ],
  };
  return {
    api: {
      getMachineSettings: vi.fn(async () => ({
        providers: {
          anthropic_api_key: "sk-ant-real",
          openai_api_key: "sk-real",
          openrouter_api_key: "",
          ollama_host: "http://127.0.0.1:11434",
        },
        default_provider: "anthropic",
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
    render(ProviderTierPicker, { props: { policy: "cloud-allowed", onChange } });

    // onMount picks the first provider when the entry is fresh and emits it.
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "anthropic", tier: "", model: "" }),
      ),
    );
  });

  it("resolves the tier against the NEWLY selected provider's catalogue, not the old one", async () => {
    // onProviderChange resolves the default tier from the list `loadModels`
    // just returned (via the pure `resolveTier`), so it always reflects the
    // just-loaded provider. The pre-runes `$:` version read stale derived data
    // here and would have resolved to the previous provider's model
    // ("claude-bal"); the correct result is the new provider's "gpt-bal".
    const onChange = vi.fn();
    render(ProviderTierPicker, { props: { policy: "cloud-allowed", onChange } });
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
        // The chosen model's display name rides along for the default hire name (#1412).
        modelLabel: "GPT Balanced",
      }),
    );
  });
});

describe("ProviderTierPicker — policy scoping (ADR-0073 S2)", () => {
  it("shows a calm nudge instead of the provider select when no provider is eligible, without emitting a bogus provider", async () => {
    const onChange = vi.fn();
    render(ProviderTierPicker, { props: { policy: "off", onChange } });

    await vi.waitFor(() =>
      expect(
        screen.getByText(/No AI providers available under this project's policy/),
      ).toBeTruthy(),
    );
    expect(screen.queryByLabelText("Subscription")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("still shows a stored provider the current policy no longer permits, flagged rather than dropped", async () => {
    const onChange = vi.fn();
    render(ProviderTierPicker, {
      props: { provider: "openrouter", policy: "local-only", onChange },
    });

    // The eligible "ollama" option only appears once the mocked
    // getMachineSettings() promise resolves — wait for it rather than the
    // select's `value`, which already reads "openrouter" from the initial
    // synchronous render (the prop's starting value) before that happens.
    await screen.findByRole("option", { name: "Ollama" });
    const subscription = screen.getByLabelText("Subscription") as HTMLSelectElement;
    expect(subscription.value).toBe("openrouter");
    expect(
      screen.getByText(/OpenRouter \(not allowed by policy\)/),
    ).toBeTruthy();
  });
});

describe("ProviderTierPicker — the model View (ADR-0073 S3)", () => {
  it("renders the catalogue as rows through ViewNodeList, and a click emits the model", async () => {
    // The Advanced exact-model list is no longer a <select> but a read-only
    // built-in View. A pane that DISPLAYS data owes a mount test that the rows
    // actually render (#642): assert the model surfaces as a row, then that
    // clicking it reports that model id through onChange.
    const onChange = vi.fn();
    render(ProviderTierPicker, { props: { policy: "cloud-allowed", onChange } });

    // The row renders the model's display name (its EvalNode `title`), sourced
    // from the mocked catalogue for the default provider.
    const row = await screen.findByText("Claude Balanced");
    onChange.mockClear();
    await fireEvent.click(row);

    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "anthropic", model: "claude-bal" }),
      ),
    );
  });

  it("badges a live-only (unverified) model as 'new'", async () => {
    // ADR-0073 S4: a model surfaced from live discovery with no baked-in audit
    // entry carries verified=false and must read as new in the row.
    render(ProviderTierPicker, { props: { policy: "cloud-allowed", onChange: vi.fn() } });
    await screen.findByText("Claude Unlisted");
    expect(screen.getByText("new")).toBeTruthy();
  });
});

describe("ProviderTierPicker — picked-model feedback (#1453)", () => {
  it("names the model in the Capability label and a read-only readout for a custom pick", async () => {
    // Picking an explicit model that is NOT any tier's resolution (claude-unlisted
    // is pricier than claude-bal, so 'balanced' resolves to claude-bal) clears the
    // tier → Custom mode. Previously that showed a bare "Custom (Advanced)" and hid
    // the very model just chosen; now the label names it and a read-only row shows
    // the exact id the entry stores.
    render(ProviderTierPicker, { props: { policy: "cloud-allowed", onChange: vi.fn() } });

    const row = await screen.findByText("Claude Unlisted");
    await fireEvent.click(row);

    // The Capability dropdown's Custom option names the model instead of "Custom (Advanced)".
    await screen.findByRole("option", { name: "Custom — Claude Unlisted" });
    // The read-only readout shows the exact model id (unique to the readout — the
    // row shows the display name, not the id).
    await vi.waitFor(() => expect(screen.getByText("claude-unlisted")).toBeTruthy());
  });
});
