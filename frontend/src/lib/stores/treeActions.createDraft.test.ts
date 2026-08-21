// ADR-0046 §6.4 / ADR-0048 §5 (#1120) — createNodeFromDraft is the create branch
// of a brainstorm: a from-scratch AI draft (title + fields + body) with no prior
// state, minted through the kind's existing create path then PUT with the drafted
// content, then opened. What these tests pin: the proposed `title` is routed to the
// top-level title and NOT duplicated into metadata; a title-less draft falls back to
// a typed default; body defaults to ""; the create is dispatched to the right kind
// (lore vs plot card); and a structural kind is refused, not silently 422'd.
import { beforeEach, describe, expect, it, vi } from "vitest";

import { treeActions } from "./treeActions.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "./editorPanes.svelte";
import { metadataSchemaStore } from "./schema";
import type { CardEntry, LoreEntry, LoreEntryList, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  entry_types: { "lore:character": { name: "Character" }, "plot:card": { name: "Card" } },
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

function mintedCard(title: string): CardEntry {
  return {
    id: "plot_new",
    title,
    body: "",
    revision: "r0",
    entry_type: "plot:card",
    metadata: {},
    computed_metadata: {},
  } as unknown as CardEntry;
}

describe("treeActions.createNodeFromDraft (ADR-0046 §6.4 / ADR-0048 §5)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
    // Mirror App's run(): it swallows a thrown API error and reports false
    // rather than rethrowing — the reason createNodeFromDraft must return
    // the outcome so the caller can keep the draft on failure.
    treeActions.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
    vi.spyOn(api, "createLoreEntry").mockImplementation(async (title: string) =>
      mintedEntry(title),
    );
    vi.spyOn(api, "saveLoreEntry").mockImplementation(async (entry: LoreEntry) => entry);
    vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] } as LoreEntryList);
    vi.spyOn(editorPanes, "openLore").mockResolvedValue(undefined as never);
    // Plot-card path: mint + save + open + the board refresh it triggers.
    vi.spyOn(api, "createCard").mockImplementation(async (title: string) => mintedCard(title));
    vi.spyOn(api, "saveCard").mockImplementation(async (entry: CardEntry) => entry);
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue({} as never);
    vi.spyOn(editorPanes, "openPlotCard").mockResolvedValue(undefined as never);
  });

  it("routes the proposed title top-level and keeps it out of metadata", async () => {
    const createdId = await treeActions.createNodeFromDraft("lore:character", {
      body: "A wandering knight.",
      fields: { title: "Seren", allegiance: "order" },
    });

    // The created {id, title} is the return value — the caller stamps the id
    // as the brainstorm chat's subject and retitles with the title (#983).
    expect(createdId).toEqual({ id: "lore_new", title: "Seren" });
    expect(api.createLoreEntry).toHaveBeenCalledWith("Seren", "lore:character");
    const [savedEntry, savedBody] = vi.mocked(api.saveLoreEntry).mock.calls[0];
    expect(savedEntry.metadata).toEqual({ allegiance: "order" });
    expect(savedEntry.metadata).not.toHaveProperty("title");
    expect(savedBody).toBe("A wandering knight.");
    expect(editorPanes.openLore).toHaveBeenCalledWith("lore_new");
  });

  it("creates a plot card from a draft, not a lore entry (#1120)", async () => {
    // A commit.target of plot:card dispatches to the card create/save/open path
    // — the whole point of generalizing the writeback beyond lore.
    const createdId = await treeActions.createNodeFromDraft("plot:card", {
      body: "She spills his coffee.",
      fields: { title: "They Meet", page_status: "sketch" },
    });

    expect(createdId).toEqual({ id: "plot_new", title: "They Meet" });
    expect(api.createCard).toHaveBeenCalledWith("They Meet");
    expect(api.createLoreEntry).not.toHaveBeenCalled();
    const [savedEntry, savedBody] = vi.mocked(api.saveCard).mock.calls[0];
    expect(savedEntry.metadata).toEqual({ page_status: "sketch" });
    expect(savedEntry.metadata).not.toHaveProperty("title");
    expect(savedBody).toBe("She spills his coffee.");
    expect(editorPanes.openPlotCard).toHaveBeenCalledWith("plot_new");
    expect(editorPanes.openLore).not.toHaveBeenCalled();
  });

  it("refuses a structural kind and mints nothing (#1120)", async () => {
    // A flat brainstorm draft has no tree position, so a manuscript scene can't
    // be created this way — fail clearly instead of 422-ing on the lore endpoint.
    const createdId = await treeActions.createNodeFromDraft("manuscript:scene", {
      body: "b",
      fields: { title: "An Opening" },
    });
    expect(createdId).toBeNull();
    expect(api.createLoreEntry).not.toHaveBeenCalled();
    expect(api.createCard).not.toHaveBeenCalled();
  });

  it("returns null and does not open a pane when the save fails", async () => {
    // run() swallows the rejection and reports false; the caller keeps the
    // draft rather than dropping it silently (code-review finding), and must
    // not stamp a subject for an entry that wasn't created (#983).
    vi.mocked(api.saveLoreEntry).mockRejectedValueOnce(new Error("409 conflict"));
    const createdId = await treeActions.createNodeFromDraft("lore:character", {
      body: "b",
      fields: { title: "Seren" },
    });
    expect(createdId).toBeNull();
    expect(editorPanes.openLore).not.toHaveBeenCalled();
  });

  it("still returns the id when a post-create step fails — the entry exists", async () => {
    // The id must not be gated on run()'s overall outcome: after the save
    // lands the entry is real, and reporting null would leave the caller's
    // draft live (duplicate mint on re-click) and skip the subject stamp
    // for an entry that exists (#983).
    vi.mocked(editorPanes.openLore).mockRejectedValueOnce(new Error("transient"));
    const createdId = await treeActions.createNodeFromDraft("lore:character", {
      body: "b",
      fields: { title: "Seren" },
    });
    expect(createdId).toEqual({ id: "lore_new", title: "Seren" });
  });

  it("falls back to a typed default title when the draft names none", async () => {
    await treeActions.createNodeFromDraft("lore:character", {
      body: null,
      fields: { allegiance: "chaos" },
    });

    expect(api.createLoreEntry).toHaveBeenCalledWith("New Character", "lore:character");
    const [savedEntry, savedBody] = vi.mocked(api.saveLoreEntry).mock.calls[0];
    expect(savedEntry.metadata).toEqual({ allegiance: "chaos" });
    expect(savedBody).toBe(""); // null body defaults to empty
  });

  it("ignores a blank proposed title and uses the default", async () => {
    await treeActions.createNodeFromDraft("lore:character", {
      body: "b",
      fields: { title: "   " },
    });
    expect(api.createLoreEntry).toHaveBeenCalledWith("New Character", "lore:character");
  });
});
