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

function mount(metadata: EntryMetadata) {
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
});
