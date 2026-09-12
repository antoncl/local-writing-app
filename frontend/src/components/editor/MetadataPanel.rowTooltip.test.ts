// @vitest-environment happy-dom
// #1900 — a field's description is the whole row's tooltip: hovering the name
// OR the value control shows it. A field without a description has no title.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";

// An assistant-kind panel reads the machine's providers on mount; tests never
// touch the network (#973).
vi.mock("@/lib/api", () => ({
  api: {
    getMachineSettings: vi.fn(async () => ({
      providers: { anthropic_api_key: "", openai_api_key: "", openrouter_api_key: "", ollama_host: "" },
      default_provider: "anthropic",
    })),
    listAIProviderModels: vi.fn(async () => ({ models: [] })),
  },
}));

import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const REACH = "How far the app reaches for lore it adds on its own.";

const SCHEMA = {
  version: 1,
  entry_types: { "assistant:assistant": { name: "Assistant", kind: "assistant", fields: ["reach", "alias"] } },
  fields: {
    reach: {
      name: "Lore reach",
      description: REACH,
      type: "select",
      default: "one_hop",
      options: [
        { value: "one_hop", label: "One hop" },
        { value: "named", label: "Named only" },
      ],
    },
    alias: { name: "Alias", type: "text" },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata) {
  render(MetadataPanel, {
    props: {
      entryType: "assistant:assistant",
      status: "",
      metadata,
      documentKind: "assistant",
      documentLabel: "Assistant",
      documentEntryTypes: [["assistant:assistant", SCHEMA.entry_types["assistant:assistant"]]] as never,
      metadataFieldIds: ["reach", "alias"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — the description is the row's tooltip (#1900)", () => {
  it("a described field's row carries the description; the name span does not repeat it", () => {
    mount({});
    const row = rowFor("Lore reach");
    expect(row.getAttribute("title")).toBe(REACH);
    expect(screen.getByText("Lore reach").getAttribute("title")).toBeNull();
    // The value control sits inside the row, so hovering it shows the same text.
    expect(row.querySelector(".fr-val")).not.toBeNull();
    expect(row.querySelector(".fr-val")?.closest("[title]")).toBe(row);
  });

  it("a field without a description has no tooltip", () => {
    mount({});
    expect(rowFor("Alias").hasAttribute("title")).toBe(false);
  });

  it("a select with a default shows the default at rest, not (none)", () => {
    mount({});
    const row = rowFor("Lore reach");
    expect(row.textContent).toContain("One hop");
    expect(row.textContent).not.toContain("(none)");
  });
});
