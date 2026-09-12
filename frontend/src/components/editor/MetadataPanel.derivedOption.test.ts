// @vitest-environment happy-dom
// #1906: a select holding a `derived` option — a state the app set (a plot
// card's On the page from its scene link) — is read-only in the rail: no edit
// hit target, the control disabled. A card at an authored state edits as usual.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "plot:card": { name: "Card", kind: "plot", fields: ["page_status"] } },
  fields: {
    page_status: {
      name: "Page status",
      type: "select",
      default: "unwritten",
      options: [
        { value: "unwritten", label: "Unwritten" },
        { value: "off_page", label: "Off the page" },
        { value: "on_page", label: "On the page", derived: true },
      ],
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata) {
  render(MetadataPanel, {
    props: {
      entryType: "plot:card",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Card",
      documentEntryTypes: [["plot:card", SCHEMA.entry_types["plot:card"]]] as never,
      metadataFieldIds: ["page_status"],
      onMetadataChange: vi.fn(),
    },
  });
}

describe("MetadataPanel — a derived option makes the field read-only (#1906)", () => {
  it("holding the derived state: no edit hit target, the select is disabled and shows the label", () => {
    mount({ page_status: "on_page" });
    expect(screen.queryByRole("button", { name: /^Edit Page status/ })).toBeNull();
    const trigger = screen.getByRole("button", { name: "Page status" });
    expect(trigger).toBeDisabled();
    expect(trigger.textContent).toContain("On the page");
  });

  it("holding an authored state (or the default): the row edits as usual", () => {
    mount({ page_status: "off_page" });
    expect(screen.getByRole("button", { name: /^Edit Page status/ })).toBeInTheDocument();
  });

  it("at rest on the default: the row edits as usual", () => {
    mount({});
    expect(screen.getByRole("button", { name: /^Edit Page status/ })).toBeInTheDocument();
  });
});
