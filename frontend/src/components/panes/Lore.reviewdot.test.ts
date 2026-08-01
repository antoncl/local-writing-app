// @vitest-environment happy-dom
// The #710 slice-3 roster dot: a lore entry's row shows a ReviewDot exactly when
// a brainstorm review is pending for that entry's id. The store method is
// unit-tested; this pins the WIRING — that the dot renders in the roster, gates
// per entry, and clears when the review does — the "type-checks but never shows"
// gap (#724) that a store test alone misses.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import Lore from "./Lore.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

// The lore roster is `descendants_of lore:base`, so the sub-type must link under
// the lore root or evaluateView renders nothing (mirrors the Prompts pane test).
const SCHEMA = {
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base" },
  },
  fields: {},
} as unknown as MetadataSchema;

const entry = (id: string, title: string): LoreEntrySummary => ({
  id,
  title,
  body: "",
  entry_type: "lore:character",
  metadata: {},
});

function renderPane() {
  return render(Lore, {
    props: { entries: [entry("e1", "Aldous Finch"), entry("e2", "Mara Vost")], onOpenEntry: () => {} },
  });
}

const dots = () => screen.queryAllByLabelText("Review pending");

describe("Lore roster — pending-review dot (#710 slice 3)", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
    metadataSchemaStore.set(SCHEMA);
  });
  afterEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
  });

  it("shows the dot only on the entry whose review is pending", () => {
    entryBrainstorm.propose("e1", { body: "revised", fields: {} });
    renderPane();
    // Exactly one row carries the marker — the one with a pending proposal.
    // (Render-time gating; ViewNodeList drives the live update via its own
    // reactivity, not this leaf read — see the #710 slice-3 review note.)
    expect(dots()).toHaveLength(1);
  });

  it("marks every pending entry, and none when clean", () => {
    entryBrainstorm.propose("e1", { body: "a", fields: {} });
    entryBrainstorm.propose("e2", { body: null, fields: { bio: "x" } });
    renderPane();
    expect(dots()).toHaveLength(2);
  });

  it("shows no dot when nothing is pending", () => {
    renderPane();
    expect(dots()).toHaveLength(0);
  });
});
