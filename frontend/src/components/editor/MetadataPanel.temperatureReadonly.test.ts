// @vitest-environment happy-dom
// #1554: when the selected assistant model dropped sampling (Anthropic Opus
// 4.7+/5, incl. the same model served through OpenRouter), the Temperature
// field renders read-only with a quiet "Not supported by the model" note. The
// model's capabilities are lifted from ProviderTierPicker (which owns the
// catalogue fetch) via onCapabilities; the note keys on the ABSENCE of the
// `temperature` capability. This guards the wiring end-to-end: catalogue →
// callback → derived → the note the author actually sees.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@/lib/test/component";

// The embedded ProviderTierPicker calls getMachineSettings() + listAIProvider
// models() on mount. Stub both; give anthropic two models — one that accepts
// temperature, one that does not — so the stored ai_model decides the outcome.
vi.mock("@/lib/api", () => {
  const models = [
    {
      id: "m-temp",
      display_name: "Accepts Temp",
      provider: "anthropic",
      context_window: 200000,
      tier: "balanced",
      capabilities: ["temperature"],
      deprecated: false,
      cost_in_per_mtok: 3,
      family: "claude",
      free: false,
      verified: true,
    },
    {
      id: "m-notemp",
      display_name: "No Sampling",
      provider: "anthropic",
      context_window: 200000,
      tier: "premium",
      capabilities: [],
      deprecated: false,
      cost_in_per_mtok: 5,
      family: "claude",
      free: false,
      verified: true,
    },
  ];
  return {
    api: {
      getMachineSettings: vi.fn(async () => ({
        providers: {
          anthropic_api_key: "sk-ant-real",
          openai_api_key: "",
          openrouter_api_key: "",
          ollama_host: "",
        },
        default_provider: "anthropic",
      })),
      listAIProviderModels: vi.fn(async () => ({ models })),
    },
  };
});

import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { aiSettings } from "@/lib/stores/aiSettings.svelte";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "assistant:default": {
      name: "Assistant",
      kind: "assistant",
      fields: ["ai_provider", "ai_capability_tier", "ai_model", "ai_temperature"],
    },
  },
  fields: {
    ai_provider: { name: "Provider", type: "text" },
    ai_capability_tier: { name: "Tier", type: "text" },
    ai_model: { name: "Model", type: "text" },
    ai_temperature: { name: "Temperature", type: "number" },
  },
} as unknown as MetadataSchema;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  aiSettings.resolvedPolicy = "cloud-allowed";
});

function mount(metadata: EntryMetadata, onMetadataChange?: (m: EntryMetadata) => void) {
  const { container } = render(MetadataPanel, {
    props: {
      entryType: "assistant:default",
      status: "",
      metadata,
      documentKind: "assistant",
      documentLabel: "Assistant",
      documentEntryTypes: [
        ["assistant:default", SCHEMA.entry_types["assistant:default"]],
      ] as never,
      metadataFieldIds: ["ai_provider", "ai_capability_tier", "ai_model", "ai_temperature"],
      effectiveOverrides: null,
      onMetadataChange,
    },
  });
  return container;
}

describe("MetadataPanel — Temperature read-only for no-sampling models (#1554)", () => {
  it("shows the 'Not supported' note when the selected model lacks temperature", async () => {
    const container = mount({ ai_provider: "anthropic", ai_model: "m-notemp" });
    await vi.waitFor(() => {
      const note = container.querySelector(".fr-temp-note");
      expect(note).not.toBeNull();
      expect(note?.textContent).toContain("Not supported by the model");
    });
  });

  it("leaves Temperature editable (no note) when the model accepts it", async () => {
    const container = mount({ ai_provider: "anthropic", ai_model: "m-temp" });
    // Give the picker's async load + the onCapabilities effect time to settle,
    // then assert the note never appears for a temp-ok model.
    await vi.waitFor(() =>
      expect(container.querySelector("[aria-label='Temperature']")).not.toBeNull(),
    );
    expect(container.querySelector(".fr-temp-note")).toBeNull();
  });

  it("drops a stale stored temperature when the model rejects it", async () => {
    // A value left over from a temp-ok model must not survive a switch to a
    // no-sampling one — otherwise it 400s on send / is rejected at save (#1554).
    const onMetadataChange = vi.fn();
    mount(
      { ai_provider: "anthropic", ai_model: "m-notemp", ai_temperature: 0.7 },
      onMetadataChange,
    );
    await vi.waitFor(() => expect(onMetadataChange).toHaveBeenCalled());
    const lastArg = onMetadataChange.mock.calls.at(-1)?.[0];
    expect(lastArg).not.toHaveProperty("ai_temperature");
  });

  it("announces the discarded temperature instead of dropping it silently (#1579)", async () => {
    // When a stored temperature is discarded because the model rejects sampling,
    // the author is TOLD — a "Temperature cleared" notice naming the model —
    // rather than the value just vanishing behind the quiet "Not supported" note.
    const container = mount(
      { ai_provider: "anthropic", ai_model: "m-notemp", ai_temperature: 0.7 },
      vi.fn(),
    );
    await vi.waitFor(() => {
      const note = container.querySelector(".fr-temp-cleared");
      expect(note).not.toBeNull();
      expect(note?.textContent).toContain("Temperature cleared");
      expect(note?.textContent).toContain("m-notemp");
    });
    // The cleared notice REPLACES the quiet state note (not both at once).
    expect(container.textContent).not.toContain("Not supported by the model");
  });

  it("keeps a stored temperature when the model accepts it", async () => {
    // The clear is gated on the model actually rejecting temperature — a temp-ok
    // model must never have its value dropped.
    const onMetadataChange = vi.fn();
    const container = mount(
      { ai_provider: "anthropic", ai_model: "m-temp", ai_temperature: 0.7 },
      onMetadataChange,
    );
    await vi.waitFor(() =>
      expect(container.querySelector("[aria-label='Temperature']")).not.toBeNull(),
    );
    // No clear-emitting call that strips ai_temperature.
    for (const [arg] of onMetadataChange.mock.calls) {
      expect(arg).toHaveProperty("ai_temperature");
    }
  });
});
