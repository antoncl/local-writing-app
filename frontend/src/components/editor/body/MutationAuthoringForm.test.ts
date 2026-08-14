// @vitest-environment happy-dom
// Apply-time pin filter (ADR-0055 §3): the "Apply a saved set" picker offers a
// PINNED set only for its own entity — never a different character of the same
// type — while a reusable (un-pinned) set is offered for every matching entity.
// This is what makes applying a pinned set pre-fill the right entity instead of
// mis-targeting.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import MutationAuthoringForm from "./MutationAuthoringForm.svelte";
import { api } from "@/lib/api";
import type { LoreEntrySummary, MetadataSchema, MutationSetEntryList } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

function lore(id: string, title: string): LoreEntrySummary {
  return { id, title, entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary;
}

function setSummary(id: string, title: string, target_entity: string) {
  return {
    id,
    title,
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity,
    row_count: 1,
    source_layer_id: "",
    source_layer_label: "",
  };
}

const NOOP = () => {};

afterEach(() => vi.restoreAllMocks());

describe("MutationAuthoringForm — pinned-set apply filter (ADR-0055 §3)", () => {
  it("offers a reusable set and this entity's pinned set, but not another entity's pin", async () => {
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({
      entries: [
        setSummary("wolf", "Mira's werewolf turn", "mira"),
        setSummary("scar", "Bob's scar", "bob"),
        setSummary("promo", "Any promotion", ""),
      ],
    } as MutationSetEntryList);
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });

    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira"), lore("bob", "Bob")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onSubmit: NOOP,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    // Switch to the apply-a-saved-set list.
    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();

    expect(screen.getByText("Mira's werewolf turn")).toBeInTheDocument();
    expect(screen.getByText("Any promotion")).toBeInTheDocument();
    // Bob's pinned set must NOT be offered when authoring against Mira.
    expect(screen.queryByText("Bob's scar")).toBeNull();
  });
});
