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
import { encodeItem } from "@/lib/editor-core/mutationListEdit";
import type {
  LoreEntrySummary,
  MetadataSchema,
  MutationSetEntry,
  MutationSetEntryList,
} from "@/lib/types";

// The apply/capture write-backs refresh or fold into this store; stub it so
// the component test does not touch the real roster.
vi.mock("@/lib/stores/mutationSets", () => ({
  refreshMutationSetEntries: vi.fn(),
  upsertMutationSet: vi.fn(),
}));

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

function lore(id: string, title: string): LoreEntrySummary {
  return { id, title, entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary;
}

function setSummary(id: string, title: string, target_entity: string, active = false) {
  return {
    id,
    title,
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity,
    row_count: 1,
    anchors: active ? [{ anchor_id: "a1", scene_id: "s1", scene_title: "Ch 1" }] : [],
    state: active ? "active" : target_entity ? "staged" : "template",
    pin_missing: false,
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
    rows: [{ id: "row1", field: "title", op: "replace", value: "The Wolf" }],
    anchors: [],
    state: target_entity ? "staged" : "template",
    pin_missing: false,
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

// C2: ADR-0095 §2 retires the stored `placed` flag and its `/place` route —
// a set's state is now DERIVED from its anchors, and applying a saved set is
// rebuilt in §6 to anchor the set itself (`insertAnchor`) rather than
// stamping its rows into a fresh unit + flipping a flag. Until that lands,
// `applySet` (MutationAuthoringForm.svelte) only filters out already-active
// sets and refreshes the roster — these tests pin that reduced contract.
describe("MutationAuthoringForm — apply picker excludes active sets (ADR-0095 §2, C2 stub)", () => {
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

  it("does not offer an already-active pinned set", async () => {
    await renderWithApplyList([
      setSummary("wolf", "Mira's werewolf turn", "mira"),
      setSummary("done", "Mira's old scar (active)", "mira", true),
    ]);
    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    expect(screen.getByText("Mira's werewolf turn")).toBeInTheDocument();
    expect(screen.queryByText("Mira's old scar (active)")).toBeNull();
  });

  it("refreshes the roster after applying a set, without a place call", async () => {
    const onSubmit = await renderWithApplyList([setSummary("wolf", "Mira's werewolf turn", "mira")]);
    vi.spyOn(api, "getMutationSetEntry").mockResolvedValue(fullSet("wolf", "mira"));

    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Mira's werewolf turn/ }));
    await tick();
    await tick();

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe("MutationAuthoringForm — dialog-own baseline position (ADR-0089 §4)", () => {
  it("fetches the effective state at the passed position, not the end of scene", async () => {
    const effective = vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: 42,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        position: 42,
        onSubmit: NOOP,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    expect(effective).toHaveBeenCalledWith("mira", "scene1", 42, []);
  });
});

describe("MutationAuthoringForm — reference-keyed list item editing (ADR-0089 §5, #2072)", () => {
  const KEYED_SCHEMA = {
    version: 1,
    entry_types: {
      "lore:character": { name: "Character", kind: "lore", fields: ["relationships"] },
    },
    fields: {
      relationships: {
        name: "Relationships",
        type: "list",
        options: [],
        item_members: [
          { key: "to", name: "To", type: "entity_ref" },
          { key: "active", name: "Active", type: "boolean" },
        ],
      },
    },
  } as unknown as MetadataSchema;

  function renderKeyedUnit() {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      // The baseline EXCLUDES this unit's own records (lore_a, the replace on
      // lore_c) — the server-side `exclude` contract (#71, ADR-0017 for the
      // collection case; the same fetch serves the item-edit baseline).
      values: {
        relationships: [
          { to: "lore_c", active: true },
          { to: "lore_d", active: true },
        ],
      },
    });
    const onSubmit = vi.fn();
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: KEYED_SCHEMA,
        sceneId: "scene1",
        initial: {
          markerId: "m1",
          entity: "mira",
          name: "",
          rows: [
            { id: "rec_add_a", field: "relationships", op: "add", value: encodeItem({ to: "lore_a", active: true }) },
            { id: "rec_replace_c", field: "relationships.lore_c.active", op: "replace", value: "false" },
          ],
        },
        onSubmit,
        onCancel: NOOP,
      },
    });
    return onSubmit;
  }

  it("seeds the keyed field from the composed effective items — the baseline plus this unit's own prior records", async () => {
    renderKeyedUnit();
    await tick();
    await tick();

    // lore_c and lore_d come from the baseline; lore_a from this unit's own
    // prior `add` record — all three visible without any interaction.
    expect(screen.getByText("lore_c")).toBeInTheDocument();
    expect(screen.getByText("lore_d")).toBeInTheDocument();
    expect(screen.getByText("lore_a")).toBeInTheDocument();
  });

  it("emits add/replace/remove with preserved ids on submit", async () => {
    const onSubmit = renderKeyedUnit();
    await tick();
    await tick();

    // Remove the baseline item lore_d (items render in composed order:
    // lore_c, lore_d, lore_a).
    const removeButtons = screen.getAllByRole("button", { name: "Remove item" });
    await fireEvent.click(removeButtons[1]);

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const draft = onSubmit.mock.calls[0][0];
    expect(draft.rows).toEqual(
      expect.arrayContaining([
        // The add is unchanged — reuses its existing id.
        { id: "rec_add_a", field: "relationships", op: "add", value: encodeItem({ to: "lore_a", active: true }) },
        // The replace re-derives from raw baseline vs the composed value —
        // still differs (true → false), so it's re-emitted, reusing its id.
        { id: "rec_replace_c", field: "relationships.lore_c.active", op: "replace", value: "false" },
        // A fresh remove for the baseline item just deleted — no prior id.
        { field: "relationships", op: "remove", value: "lore_d" },
      ]),
    );
    expect(draft.rows).toHaveLength(3);
  });
});
