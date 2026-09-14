// Shared harness for the NodePicker.*.test.ts files, split apart for the
// 1500-line file-size cap. The SCHEMA, entry factories, the expand-a-collapsed-
// group helper, and the per-test store setup/teardown live here so every split
// file runs in a byte-identical environment.
import { vi } from "vitest";
import { tick } from "svelte";
import { fireEvent, within } from "@/lib/test/component";
import { api } from "@/lib/api";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import { cardEntriesStore } from "@/lib/stores/plotCards";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { LoreEntrySummary, MetadataSchema, PlotlineSummary, PromptEntrySummary } from "@/lib/types";

export const SCHEMA = {
  entry_types: {
    "prompt:snippet": { name: "Snippet", kind: "prompt" },
    "prompt:voice_note": { name: "Voice note", kind: "prompt", parent: "prompt:snippet" },
    "prompt:general": { name: "General", kind: "prompt" },
    "plot:plotline": { name: "Plotline", kind: "plot" },
    "plot:card": { name: "Card", kind: "plot" },
    "lore:character": { name: "Character", kind: "lore" },
    // A user specialization of character (#1945): a character scope must include it (is-a).
    "lore:character:deity": { name: "Deity", kind: "lore", parent: "lore:character" },
    "tag:tag": { name: "Tag", kind: "tag" },
    "tag:assistant_tag": { name: "Assistant tag", kind: "tag" },
    "tag:base": { name: "Tag", kind: "tag", abstract: true },
  },
  fields: {},
} as unknown as MetadataSchema;

// A plot card summary shape (metadata.plotline is the scalar membership ref).
export function plotCard(id: string, title: string, plotlineId: string | null) {
  return {
    id,
    title,
    body: "",
    entry_type: "plot:card",
    metadata: plotlineId ? { plotline: plotlineId } : {},
  } as never;
}

export function loreEntry(id: string, title: string, tags: string[], aliases: string[] = []) {
  return {
    id,
    title,
    body: "",
    entry_type: "lore:character",
    metadata: { tags, aliases },
  } as unknown as LoreEntrySummary;
}

export function snippet(id: string, title: string, entryType = "prompt:snippet"): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: entryType,
    metadata: {},
    computed_metadata: {},
    inputs: [],
    is_library: true,
  };
}

export function plotline(id: string, title: string): PlotlineSummary {
  return { id, title, body: "", entry_type: "plot:plotline", metadata: {} };
}

// Collapse-by-default (#1520): every container (act/chapter, tag, view, plotline,
// lore entry-type) opens collapsed, so a test that wants to see or click a member
// first expands the container by its caret ("Expand <title>").
export async function expandGroup(scope: HTMLElement, title: string) {
  await fireEvent.click(within(scope).getByRole("button", { name: `Expand ${title}` }));
  await tick();
}

// Per-test store setup: the picker reads saved views from the `paneViews` roster
// (ADR-0074 Amendment 3 — no fetch); reset it per test and seed it where a test
// exercises views. Tags come from tagNodesStore (no fetch) — empty by default.
// The api.listViews stub stays as a belt so no transitive path touches the
// network (#973).
export function setupNodePicker() {
  localStorage.clear();
  openProjectHidden("nodepicker-test");
  metadataSchemaStore.set(SCHEMA);
  vi.spyOn(api, "listViews").mockResolvedValue({ entries: [] });
  paneViews.reset();
  tagNodesStore.set([]);
  cardEntriesStore.set([]);
}

export function teardownNodePicker() {
  openProjectHidden(null);
  localStorage.clear();
  paneViews.reset();
  tagNodesStore.set([]);
  cardEntriesStore.set([]);
  vi.restoreAllMocks();
}
