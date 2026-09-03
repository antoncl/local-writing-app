// The context_strategy write path (ADR-0065 S3 / ADR-0062 D3). PromptOutputEditor
// authors an instance-level behavior contract that must (a) ride the prompt save
// to the wire, and (b) survive a body-only edit — the data-loss bug D3 closes: a
// save that omits context_strategy silently wipes a forked prompt's output/commit
// config (the writer rebuilds front matter from its args, not a merge).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { api } from "@/lib/api";
import type { MetadataSchema, PromptContextStrategy, PromptEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "prompt:general": { name: "General", kind: "prompt", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

const BASELINE_STRATEGY: PromptContextStrategy = {
  output: { handler: "extract_to_node", commit: { review: "replace" } },
};

const BASELINE = {
  id: "prompt_1",
  title: "Summarize scene",
  body: "Summarize the scene.",
  revision: "r1",
  entry_type: "prompt:general",
  metadata: {},
  computed_metadata: {},
  inputs: [],
  offer_on: [],
  context_strategy: BASELINE_STRATEGY,
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
      draftOfferOn: [],
      draftContextStrategy: BASELINE_STRATEGY,
      dirty: true,
      ...over,
    },
  ];
}

function stubRefreshes(): void {
  vi.spyOn(api, "listPromptEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "getKnownTags").mockResolvedValue({ tags: [] });
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
}

describe("editorPanes context_strategy write path (ADR-0062 D3)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
  });

  afterEach(() => {
    editorPanes.reset();
    metadataSchemaStore.set(null);
  });

  it("carries the edited context_strategy onto the prompt save", async () => {
    const edited: PromptContextStrategy = { output: { handler: "inline", destination: "selection" } };
    seedPromptPane({ draftContextStrategy: edited });
    stubRefreshes();
    let captured: PromptContextStrategy | null | undefined;
    vi.spyOn(api, "savePromptEntry").mockImplementation((entry) => {
      captured = (entry as PromptEntry).context_strategy;
      return Promise.resolve({ ...BASELINE, revision: "r2", context_strategy: captured } as unknown as PromptEntry);
    });

    await editorPanes.saveEditorPane("pane_1");

    expect(captured).toEqual(edited);
  });

  it("a body-only save preserves the context_strategy baseline (no strip — the wipe fix)", async () => {
    // draftContextStrategy stays at the baseline; only the body changed.
    seedPromptPane({ draftMarkdown: "Rewritten brief." });
    stubRefreshes();
    let captured: PromptContextStrategy | null | undefined;
    vi.spyOn(api, "savePromptEntry").mockImplementation((entry) => {
      captured = (entry as PromptEntry).context_strategy;
      return Promise.resolve({ ...BASELINE, revision: "r2" } as unknown as PromptEntry);
    });

    await editorPanes.saveEditorPane("pane_1");

    expect(captured).toEqual(BASELINE_STRATEGY);
  });

  it("updateEditorPaneDraft threads the context_strategy arg and arms dirty", () => {
    seedPromptPane({ dirty: false });
    const next: PromptContextStrategy = { output: { handler: "inline" } };
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      BASELINE.title,
      BASELINE.body,
      "",
      BASELINE.entry_type,
      {},
      [],
      [],
      next,
    );
    expect(editorPanes.panes[0].draftContextStrategy).toEqual(next);
    expect(editorPanes.panes[0].dirty).toBe(true);
  });

  it("updateEditorPaneDraft preserves the current strategy when context_strategy is omitted", () => {
    seedPromptPane({ dirty: false });
    // A caller that passes no context_strategy (undefined — e.g. a non-prompt
    // pane) must not clear it.
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      BASELINE.title,
      "new body",
      "",
      BASELINE.entry_type,
      {},
      [],
      [],
      undefined,
    );
    expect(editorPanes.panes[0].draftContextStrategy).toEqual(BASELINE_STRATEGY);
  });

  it("updateEditorPaneDraft treats an explicit null as clearing the strategy", () => {
    seedPromptPane({ dirty: false });
    editorPanes.updateEditorPaneDraft(
      "pane_1",
      BASELINE.title,
      BASELINE.body,
      "",
      BASELINE.entry_type,
      {},
      [],
      [],
      null,
    );
    expect(editorPanes.panes[0].draftContextStrategy).toBeNull();
    expect(editorPanes.panes[0].dirty).toBe(true);
  });
});
