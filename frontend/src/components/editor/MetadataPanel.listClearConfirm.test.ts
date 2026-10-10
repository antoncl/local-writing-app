// @vitest-environment happy-dom
// #2437: the reset mark on a non-empty list field (tags) used to delete every
// value in one unconfirmed click. It now routes through the confirm modal, naming
// each value; nothing changes until the user confirms. A scalar keeps the
// one-click reset.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes, tagNodesStore } from "@/lib/stores/tagNodes";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import type { EntryMetadata, MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["tags", "alias"] },
    "tag:theme": { name: "Theme", kind: "tag" },
  },
  fields: {
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "tag", expr: { type: "tag:theme" } }] },
    },
    alias: { name: "Alias", type: "text" },
  },
} as unknown as MetadataSchema;

const TAGS: TagEntry[] = [
  { id: "tag_a", title: "Alpha", entry_type: "tag:theme", metadata: {} },
  { id: "tag_b", title: "Beta", entry_type: "tag:theme", metadata: {} },
];

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  tagNodesStore.set(TAGS);
});
afterEach(() => {
  clearTagNodes();
  confirmService.active = null;
});

function mount(metadata: EntryMetadata) {
  const onMetadataChange = vi.fn();
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["tags", "alias"],
      onMetadataChange,
    },
  });
  return { onMetadataChange };
}

describe("MetadataPanel — clearing a list field asks first (#2437)", () => {
  it("opens a confirm naming every tag, and clears only on confirm", async () => {
    const { onMetadataChange } = mount({ tags: ["tag_a", "tag_b"], alias: "Mi" });
    await fireEvent.click(screen.getByRole("button", { name: "Reset Tags to default" }));

    expect(onMetadataChange).not.toHaveBeenCalled();
    const request = confirmService.active;
    expect(request).toMatchObject({
      message: "Remove all 2 values from Tags?",
      details: ["Alpha", "Beta"],
      destructive: true,
      cannotBeUndone: true,
    });
    // Always asks: no "don't show this again" escape hatch.
    expect(request?.dontShowAgainKey).toBeUndefined();

    await request!.onConfirm();
    expect(onMetadataChange).toHaveBeenCalledWith({ alias: "Mi" });
  });

  it("clears a scalar straight away", async () => {
    const { onMetadataChange } = mount({ tags: ["tag_a"], alias: "Mi" });
    await fireEvent.click(screen.getByRole("button", { name: "Reset Alias to default" }));

    expect(confirmService.active).toBeNull();
    expect(onMetadataChange).toHaveBeenCalledWith({ tags: ["tag_a"] });
  });
});
