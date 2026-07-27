// forkLore flush-before-fork (#520, a regression of #313). `forkLore` severs an
// inherited lore entry into a local copy and reconciles the open pane onto the
// now-local entry — overwriting draftTitle/draftMarkdown/draftMetadata. Before
// that reconcile it MUST flush a dirty pane, or edits typed inside the 6s
// autosave debounce vanish into the void #313 called out. The guard used the
// scene-only `paneForScene`, which returns undefined for a lore pane, so the
// flush was dead for exactly the kind `forkLore` operates on.
//
// What these tests pin: forkLore flushes iff the lore pane is dirty, the flush
// carries the edited draft, and it runs BEFORE the fork call.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { api } from "@/lib/api";
import type { LoreEntry } from "@/lib/types";

const INHERITED: LoreEntry = {
  id: "lore_1",
  title: "Old Name",
  body: "body",
  revision: "r1",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
  source_layer_id: "layer_universe",
  source_layer_label: "Universe",
};

const LOCAL_FORK: LoreEntry = {
  ...INHERITED,
  revision: "r2",
  source_layer_id: undefined,
  source_layer_label: undefined,
  forked_from: "../universe",
};

// Seed one lore pane onto the singleton with an optional dirty draft edit.
function seedLorePane(dirty: boolean): void {
  const pane = {
    ...createEmptyEditorPane("pane_1"),
    document: { type: "lore" as const, id: INHERITED.id },
    scene: INHERITED,
    draftTitle: dirty ? "Edited Name" : INHERITED.title,
    draftMarkdown: INHERITED.body,
    draftEntryType: INHERITED.entry_type,
    dirty,
    authoringLayerId: "layer_book",
  };
  editorPanes.panes = [pane];
}

describe("editorPanes.forkLore flush guard (#520)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
    // refreshLoreEntries() runs inside forkLore; keep it off the network.
    vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "forkLoreEntry").mockResolvedValue(LOCAL_FORK);
  });

  afterEach(() => editorPanes.reset());

  it("flushes a dirty lore pane, carrying the edited draft, before forking", async () => {
    seedLorePane(true);
    // Capture the draft the flush would persist, without exercising the whole
    // save round-trip — the regression is that the flush never fires at all.
    let flushedTitle: string | undefined;
    const save = vi
      .spyOn(editorPanes, "saveEditorPane")
      .mockImplementation(async (id: string) => {
        flushedTitle = editorPanes.panes.find((p) => p.id === id)?.draftTitle;
      });

    await editorPanes.forkLore(INHERITED.id);

    expect(save).toHaveBeenCalledWith("pane_1");
    expect(flushedTitle).toBe("Edited Name");
    // The flush must precede the fork, or it writes back against a baseline the
    // fork has already moved.
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(
      (api.forkLoreEntry as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0],
    );
  });

  it("does not flush a clean lore pane", async () => {
    seedLorePane(false);
    const save = vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.forkLore(INHERITED.id);

    expect(save).not.toHaveBeenCalled();
    expect(api.forkLoreEntry).toHaveBeenCalledWith(INHERITED.id);
  });

  it("reconciles the pane onto the local fork and clears dirty", async () => {
    seedLorePane(true);
    vi.spyOn(editorPanes, "saveEditorPane").mockResolvedValue(undefined);

    await editorPanes.forkLore(INHERITED.id);

    const pane = editorPanes.panes.find((p) => p.id === "pane_1");
    expect(pane?.scene).toEqual(LOCAL_FORK);
    expect(pane?.dirty).toBe(false);
    expect(pane?.draftTitle).toBe(LOCAL_FORK.title);
    // A local entry owns its own file — no override target, no rail picker (#314).
    expect(pane?.authoringLayerId).toBeNull();
  });
});
