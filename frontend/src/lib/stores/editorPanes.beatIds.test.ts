import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/stores/plotBoard", () => ({ refreshPlotBoard: vi.fn(async () => {}) }));
vi.mock("@/lib/stores/plotlines", () => ({ refreshPlotlines: vi.fn(async () => {}) }));
vi.mock("@/lib/stores/references", () => ({ refreshReferenceIndexInBackground: vi.fn() }));

import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { DocumentRef } from "@/lib/editor-core/editorPaneModel";
import type { EditableDocument, MetadataSchema, PlotlineEntry } from "@/lib/types";
import { api } from "@/lib/api";
import { setMetadataSchema } from "@/lib/stores/schema";

// #2255: a beat added in the plotline DOCUMENT pane has no id; the backend
// mints one on save. Unless the pane takes it back, the draft stays dirty
// against its own save and every autosave re-mints a fresh id — forever.
// ADR-0096 §1/§2: the pane reads which field is a beat list off the schema's
// declared identity, not a hardcoded field-name list — seed one here.
const SCHEMA: MetadataSchema = {
  version: 1,
  entry_types: {
    "plot:plotline": { name: "Plotline", kind: "plot", fields: ["instance_beats"] },
  },
  fields: {
    instance_beats: { name: "Beats", type: "list", options: [], item_group: "plot_instance_beat", item_identity: "id" },
  },
} as unknown as MetadataSchema;

const HOOK = { title: "Hook", id: "hook" };

function plotlinePane(beats: Record<string, unknown>[]): void {
  const pane = createEmptyEditorPane("editor_1");
  pane.document = { type: "plotline", id: "plot_1" } as DocumentRef;
  pane.scene = {
    id: "plot_1",
    title: "Arc",
    body: "",
    entry_type: "plot:plotline",
    metadata: { instance_beats: [HOOK] },
    revision: "rev1",
  } as unknown as EditableDocument;
  pane.draftTitle = "Arc";
  pane.draftMarkdown = "";
  pane.draftEntryType = "plot:plotline";
  pane.draftMetadata = { instance_beats: beats } as never;
  pane.dirty = true;
  editorPanes.panes = [pane];
}

function savedWith(beats: Record<string, unknown>[]): PlotlineEntry {
  return {
    id: "plot_1",
    title: "Arc",
    body: "",
    entry_type: "plot:plotline",
    metadata: { instance_beats: beats },
    revision: "rev2",
  } as unknown as PlotlineEntry;
}

describe("plotline pane save adopts minted beat ids (#2255)", () => {
  beforeEach(() => {
    editorPanes.reset();
    setMetadataSchema(SCHEMA);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("a new beat takes its minted id: the pane is clean and the editor is re-seeded", async () => {
    plotlinePane([HOOK, { title: "New" }]);
    vi.spyOn(api, "savePlotline").mockResolvedValue(savedWith([HOOK, { title: "New", id: "beat_1" }]));
    const tokenBefore = editorPanes.nextMetadataReloadToken;

    await editorPanes.saveEditorPane("editor_1");

    const pane = editorPanes.panes[0];
    expect(pane.draftMetadata).toEqual({ instance_beats: [HOOK, { title: "New", id: "beat_1" }] });
    expect(pane.dirty).toBe(false);
    const reload = editorPanes.metadataReloadsByPane.editor_1;
    expect(reload?.token).toBe(tokenBefore);
    expect(reload?.metadata).toEqual(pane.draftMetadata);
  });

  it("a second save sends the adopted id, so nothing is re-minted", async () => {
    plotlinePane([HOOK, { title: "New" }]);
    const saveSpy = vi
      .spyOn(api, "savePlotline")
      .mockResolvedValue(savedWith([HOOK, { title: "New", id: "beat_1" }]));
    await editorPanes.saveEditorPane("editor_1");

    editorPanes.panes = editorPanes.panes.map((p) => ({ ...p, dirty: true }));
    await editorPanes.saveEditorPane("editor_1");

    const sent = saveSpy.mock.calls[1][0] as PlotlineEntry;
    expect(sent.metadata.instance_beats).toEqual([HOOK, { title: "New", id: "beat_1" }]);
  });

  it("a save that minted nothing sends no reload", async () => {
    plotlinePane([HOOK]);
    vi.spyOn(api, "savePlotline").mockResolvedValue(savedWith([HOOK]));

    await editorPanes.saveEditorPane("editor_1");

    expect(editorPanes.metadataReloadsByPane.editor_1).toBeUndefined();
    expect(editorPanes.panes[0].dirty).toBe(false);
  });
});
