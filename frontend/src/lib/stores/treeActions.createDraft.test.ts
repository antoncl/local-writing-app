// ADR-0046 §6.4 — createLoreEntryFromDraft is the create branch of the lore
// brainstorm: a from-scratch AI draft (title + fields + body) with no prior
// state, minted through the existing create path (POST /api/lore) then PUT with
// the drafted content, then opened. What these tests pin: the proposed `title`
// is routed to the top-level title and NOT duplicated into metadata; a
// title-less draft falls back to a typed default; body defaults to "".
import { beforeEach, describe, expect, it, vi } from "vitest";

import { treeActions } from "./treeActions.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "./editorPanes.svelte";
import { metadataSchemaStore } from "./schema";
import type { LoreEntry, LoreEntryList, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  entry_types: { "lore:character": { name: "Character" } },
  fields: {},
} as unknown as MetadataSchema;

function mintedEntry(title: string): LoreEntry {
  return {
    id: "lore_new",
    title,
    body: "",
    revision: "r0",
    entry_type: "lore:character",
    metadata: {},
    computed_metadata: {},
  } as unknown as LoreEntry;
}

describe("treeActions.createLoreEntryFromDraft (ADR-0046 §6.4)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
    vi.spyOn(api, "createLoreEntry").mockImplementation(async (title: string) =>
      mintedEntry(title),
    );
    vi.spyOn(api, "saveLoreEntry").mockImplementation(async (entry: LoreEntry) => entry);
    vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] } as LoreEntryList);
    vi.spyOn(editorPanes, "openLore").mockResolvedValue(undefined as never);
  });

  it("routes the proposed title top-level and keeps it out of metadata", async () => {
    await treeActions.createLoreEntryFromDraft("lore:character", {
      body: "A wandering knight.",
      fields: { title: "Seren", allegiance: "order" },
    });

    expect(api.createLoreEntry).toHaveBeenCalledWith("Seren", "lore:character");
    const [savedEntry, savedBody] = vi.mocked(api.saveLoreEntry).mock.calls[0];
    expect(savedEntry.metadata).toEqual({ allegiance: "order" });
    expect(savedEntry.metadata).not.toHaveProperty("title");
    expect(savedBody).toBe("A wandering knight.");
    expect(editorPanes.openLore).toHaveBeenCalledWith("lore_new");
  });

  it("falls back to a typed default title when the draft names none", async () => {
    await treeActions.createLoreEntryFromDraft("lore:character", {
      body: null,
      fields: { allegiance: "chaos" },
    });

    expect(api.createLoreEntry).toHaveBeenCalledWith("New Character", "lore:character");
    const [savedEntry, savedBody] = vi.mocked(api.saveLoreEntry).mock.calls[0];
    expect(savedEntry.metadata).toEqual({ allegiance: "chaos" });
    expect(savedBody).toBe(""); // null body defaults to empty
  });

  it("ignores a blank proposed title and uses the default", async () => {
    await treeActions.createLoreEntryFromDraft("lore:character", {
      body: "b",
      fields: { title: "   " },
    });
    expect(api.createLoreEntry).toHaveBeenCalledWith("New Character", "lore:character");
  });
});
