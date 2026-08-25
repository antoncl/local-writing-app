// @vitest-environment happy-dom
// #1421: a required select (one with a schema default) keeps front matter sparse —
// picking the default pops the key; picking a non-default writes it.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:note": { name: "Note", kind: "lore", fields: ["ctx"] } },
  fields: {
    ctx: {
      name: "Context",
      type: "select",
      default: "auto",
      options: [
        { value: "always", label: "Always" },
        { value: "auto", label: "Auto" },
        { value: "never", label: "Never" },
      ],
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata) {
  const onMetadataChange = vi.fn();
  render(MetadataPanel, {
    props: {
      entryType: "lore:note",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:note", SCHEMA.entry_types["lore:note"]]] as never,
      metadataFieldIds: ["ctx"],
      onMetadataChange,
    },
  });
  return { onMetadataChange };
}

async function pick(optionLabel: string) {
  await fireEvent.click(screen.getByRole("button", { name: "Context" })); // open
  await fireEvent.click(screen.getByRole("option", { name: optionLabel }));
}

describe("MetadataPanel — required-select stays sparse (#1421)", () => {
  it("writes a non-default pick", async () => {
    const { onMetadataChange } = mount({});
    await pick("Always");
    expect(onMetadataChange).toHaveBeenCalledWith({ ctx: "always" });
  });

  it("pops the key when the default is picked (revert to sparse)", async () => {
    const { onMetadataChange } = mount({ ctx: "always" });
    await pick("Auto"); // the schema default
    expect(onMetadataChange).toHaveBeenCalledWith({});
  });
});
