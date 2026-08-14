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
import type {
  LoreEntrySummary,
  MetadataSchema,
  MutationSetEntry,
  MutationSetEntryList,
} from "@/lib/types";

// The place write-back refreshes this store; stub it so the component test does
// not touch the real roster fetch.
vi.mock("@/lib/stores/mutationSets", () => ({ refreshMutationSetEntries: vi.fn() }));

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

function lore(id: string, title: string): LoreEntrySummary {
  return { id, title, entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary;
}

function setSummary(id: string, title: string, target_entity: string, placed = false) {
  return {
    id,
    title,
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity,
    row_count: 1,
    placed,
    source_layer_id: "",
    source_layer_label: "",
  };
}

// The full entry api.getMutationSetEntry returns when a row is applied.
function fullSet(id: string, target_entity: string): MutationSetEntry {
  return {
    id,
    title: `Set ${id}`,
    revision: "r1",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity,
    rows: [{ field: "title", op: "replace", value: "The Wolf" }],
    placed: false,
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

describe("MutationAuthoringForm — place-on-apply (ADR-0055 §5)", () => {
  async function renderWithApplyList(entries: ReturnType<typeof setSummary>[]) {
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({
      entries,
    } as MutationSetEntryList);
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    const onSubmit = vi.fn();
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onSubmit,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();
    return onSubmit;
  }

  it("does not offer a placed pinned set", async () => {
    await renderWithApplyList([
      setSummary("wolf", "Mira's werewolf turn", "mira"),
      setSummary("done", "Mira's old scar (placed)", "mira", true),
    ]);
    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    expect(screen.getByText("Mira's werewolf turn")).toBeInTheDocument();
    expect(screen.queryByText("Mira's old scar (placed)")).toBeNull();
  });

  it("marks a PINNED set placed after it is applied", async () => {
    const onSubmit = await renderWithApplyList([setSummary("wolf", "Mira's werewolf turn", "mira")]);
    vi.spyOn(api, "getMutationSetEntry").mockResolvedValue(fullSet("wolf", "mira"));
    const place = vi.spyOn(api, "placeMutationSet").mockResolvedValue(fullSet("wolf", "mira"));

    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Mira's werewolf turn/ }));
    await tick();
    await tick();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(place).toHaveBeenCalledWith("wolf"); // the one-off is consumed
  });

  it("does NOT mark a reusable set placed on apply", async () => {
    const onSubmit = await renderWithApplyList([setSummary("promo", "Any promotion", "")]);
    vi.spyOn(api, "getMutationSetEntry").mockResolvedValue(fullSet("promo", "")); // no pin
    const place = vi.spyOn(api, "placeMutationSet").mockResolvedValue(fullSet("promo", ""));

    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Any promotion/ }));
    await tick();
    await tick();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(place).not.toHaveBeenCalled(); // a reusable set stays a pure read
  });
});
