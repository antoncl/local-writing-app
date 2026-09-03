// The offer_on write path (ADR-0054 §4 / S4b). The picker authors an
// instance-level allow-list that must (a) ride the prompt save to the wire, and
// (b) survive a body-only edit — the whole point of threading a dedicated
// draftOfferOn rather than leaning on the pane.scene spread, which the save
// overrides field-by-field for prompts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { api } from "@/lib/api";
import type { MetadataSchema, PromptEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "prompt:general": { name: "General", kind: "prompt", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

const BASELINE = {
  id: "prompt_1",
  title: "Impersonate",
  body: "You ARE the character.",
  revision: "r1",
  entry_type: "prompt:general",
  metadata: {},
  computed_metadata: {},
  inputs: [],
  offer_on: ["lore:character"],
} as unknown as PromptEntry;

function seedPromptPane(over: Record<string, unknown> = {}): void {
  editorPanes.panes = [
    {
      ...createEmptyEditorPane("pane_1"),
      document: { type: "prompt" as const, id: BASELINE.id },
      scene: BASELINE,
      draftTitle: BASELINE.title,
      draftMarkdown: BASELINE.body,
      draftEntryType: BASELINE.entry_type,
      draftInputs: [],
      draftOfferOn: ["lore:character"],
      dirty: true,
      ...over,
    },
  ];
}

function stubRefreshes(): void {
  vi.spyOn(api, "listPromptEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
}

describe("editorPanes offer_on write path (S4b)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
  });

  afterEach(() => {
    editorPanes.reset();
    metadataSchemaStore.set(null);
  });

  it("carries the edited offer_on allow-list onto the prompt save", async () => {
    seedPromptPane({ draftOfferOn: ["lore:base", "plot:card"] });
    stubRefreshes();
    let capturedOfferOn: string[] | undefined;
    vi.spyOn(api, "savePromptEntry").mockImplementation((entry) => {
      capturedOfferOn = (entry as PromptEntry).offer_on;
      return Promise.resolve({ ...BASELINE, revision: "r2", offer_on: capturedOfferOn } as unknown as PromptEntry);
    });

    await editorPanes.saveEditorPane("pane_1");

    expect(capturedOfferOn).toEqual(["lore:base", "plot:card"]);
  });

  it("a body-only save preserves the offer_on baseline (no strip)", async () => {
    // draftOfferOn stays at the baseline; only the body changed.
    seedPromptPane({ draftMarkdown: "Rewritten brief." });
    stubRefreshes();
    let capturedOfferOn: string[] | undefined;
    vi.spyOn(api, "savePromptEntry").mockImplementation((entry) => {
      capturedOfferOn = (entry as PromptEntry).offer_on;
      return Promise.resolve({ ...BASELINE, revision: "r2" } as unknown as PromptEntry);
    });

    await editorPanes.saveEditorPane("pane_1");

    expect(capturedOfferOn).toEqual(["lore:character"]);
  });

  it("updateEditorPaneDraft threads the offer_on arg and arms dirty", () => {
    seedPromptPane({ dirty: false });
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      BASELINE.title,
      BASELINE.body,
      "",
      BASELINE.entry_type,
      {},
      [],
      ["lore:character", "plot:card"],
    );
    expect(editorPanes.panes[0].draftOfferOn).toEqual(["lore:character", "plot:card"]);
    expect(editorPanes.panes[0].dirty).toBe(true);
  });

  it("updateEditorPaneDraft preserves the current allow-list when offer_on is omitted", () => {
    seedPromptPane({ draftOfferOn: ["lore:base"], dirty: false });
    // A caller that passes no offer_on (undefined) must not clear it.
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      BASELINE.title,
      "new body",
      "",
      BASELINE.entry_type,
      {},
      [],
      undefined,
    );
    expect(editorPanes.panes[0].draftOfferOn).toEqual(["lore:base"]);
  });
});
