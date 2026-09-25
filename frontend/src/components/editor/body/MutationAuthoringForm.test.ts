// @vitest-environment happy-dom
// ADR-0095 §6: create mode creates the SET first (via the API) and only then
// tells the caller to insert its anchor; a failed create inserts nothing.
// Edit mode (opened on a pill click) saves the set in place — the scene
// document is never touched by this form — with the entity picker locked.
// Applying a saved set flushes open scenes + refreshes the roster first, then
// offers templates/staged/active sets with the right verb per ADR-0095 §6.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import MutationAuthoringForm from "./MutationAuthoringForm.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { metadataSchemaLayersStore } from "@/lib/stores/schema";
import { encodeItem } from "@/lib/editor-core/mutationListEdit";
import type {
  LoreEntrySummary,
  MetadataSchema,
  MetadataSchemaLayer,
  MutationSetEntry,
  MutationSetEntryList,
  MutationSetEntrySummary,
} from "@/lib/types";

// The write-backs fold into the real store (a plain Svelte store — safe to
// let run for real across these tests).
const NOOP = () => {};

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

function lore(id: string, title: string): LoreEntrySummary {
  return { id, title, entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary;
}

function setSummary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "set1",
    title: "A set",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "",
    row_count: 1,
    rows: [{ id: "r1", field: "title", op: "replace", value: "The Wolf" }],
    anchors: [],
    state: "template",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

function fullSet(over: Partial<MutationSetEntry> = {}): MutationSetEntry {
  return {
    id: "set1",
    title: "A set",
    revision: "r1",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    rows: [{ id: "row1", field: "title", op: "replace", value: "The Wolf" }],
    anchors: [],
    state: "staged",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  metadataSchemaLayersStore.set([]);
});

describe("MutationAuthoringForm — create (ADR-0095 §6)", () => {
  it("creates the set BEFORE calling onCreated (the caller inserts the anchor only after)", async () => {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
    const order: string[] = [];
    const createSpy = vi.spyOn(api, "createMutationSetEntry").mockImplementation(async () => {
      order.push("created");
      return fullSet();
    });
    const onCreated = vi.fn((_id: string) => order.push("onCreated"));

    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onCreated,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    await fireEvent.click(screen.getByRole("button", { name: "Add field change" }));
    const valueInput = screen.getByLabelText("Title (name)");
    await fireEvent.input(valueInput, { target: { value: "The Wolf" } });
    await fireEvent.click(screen.getByRole("button", { name: "Insert mutation" }));
    await tick();
    await tick();

    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ target_entity: "mira", target_entry_type: "lore:character" }),
    );
    expect(order).toEqual(["created", "onCreated"]);
    expect(onCreated).toHaveBeenCalledWith("set1");
  });

  it("a failed create inserts nothing and shows the error", async () => {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "createMutationSetEntry").mockRejectedValue(new Error("rank: not mutable for this type"));
    const onCreated = vi.fn();

    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onCreated,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    await fireEvent.click(screen.getByRole("button", { name: "Add field change" }));
    await fireEvent.input(screen.getByLabelText("Title (name)"), { target: { value: "The Wolf" } });
    await fireEvent.click(screen.getByRole("button", { name: "Insert mutation" }));
    await tick();
    await tick();

    expect(onCreated).not.toHaveBeenCalled();
    expect(await screen.findByText("rank: not mutable for this type")).toBeInTheDocument();
  });
});

describe("MutationAuthoringForm — pill edit (ADR-0095 §6)", () => {
  it("saves the set with base_revision, locks the entity picker, and calls onSaved (never onCreated)", async () => {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: 12,
      values: {},
    });
    const saveSpy = vi
      .spyOn(api, "saveMutationSetEntry")
      .mockResolvedValue(fullSet({ title: "Promotion", revision: "r2" }));
    const onSaved = vi.fn();
    const onCreated = vi.fn();

    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        initial: fullSet({ title: "Promotion" }),
        anchorId: "a1",
        sceneId: "scene1",
        position: 12,
        onCreated,
        onSaved,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    // The entity picker is read-only in edit mode (ADR-0095 §6): its
    // add/change trigger doesn't render at all.
    const entityRegion = screen.getByRole("region", { name: "Entity" });
    expect(entityRegion.querySelector(".reference-picker-trigger")).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await tick();
    await tick();

    expect(saveSpy).toHaveBeenCalledWith(expect.objectContaining({ id: "set1", revision: "r1" }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("the baseline excludes THIS anchor", async () => {
    const effective = vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: 12,
      values: {},
    });
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        initial: fullSet(),
        anchorId: "a1",
        sceneId: "scene1",
        position: 12,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    expect(effective).toHaveBeenCalledWith("mira", "scene1", 12, ["a1"]);
  });

  it("Remove from this scene calls onRemoveAnchor, not onSaved", async () => {
    const onRemoveAnchor = vi.fn();
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        initial: fullSet(),
        anchorId: "a1",
        sceneId: "scene1",
        onRemoveAnchor,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    const removeButton = screen.getByRole("button", { name: "Remove from this scene" });
    expect(removeButton).toHaveAttribute("title", "Remove from this scene");
    await fireEvent.click(removeButton);
    expect(onRemoveAnchor).toHaveBeenCalledTimes(1);
  });
});

describe("MutationAuthoringForm — apply a saved set (ADR-0095 §6)", () => {
  function entries(): MutationSetEntrySummary[] {
    return [
      setSummary({ id: "tmpl", title: "Full moon", state: "template", target_entity: "" }),
      setSummary({ id: "staged1", title: "Mira's scar", state: "staged", target_entity: "mira" }),
      setSummary({
        id: "active1",
        title: "Mira's tattoo",
        state: "active",
        target_entity: "mira",
        anchors: [{ anchor_id: "x", scene_id: "s1", scene_title: "Ch 1" }],
      }),
      setSummary({
        id: "layered1",
        title: "Series template",
        state: "template",
        target_entity: "",
        source_layer_id: "series-layer",
      }),
    ];
  }

  async function openApplyTab() {
    // Own project layer, distinct from `layered1`'s "series-layer" (#2236
    // review fix: `fromAnotherLayer` compares against this, not against
    // non-empty `source_layer_id`) — the native entries above default to
    // `source_layer_id: ""`, which never counts as inherited regardless.
    metadataSchemaLayersStore.set([
      { id: "book", label: "Book", folder_path: "", schema_path: "", exists: true },
    ] satisfies MetadataSchemaLayer[]);
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: entries() } as MutationSetEntryList);
    const flush = vi.spyOn(editorPanes, "flushDirtyPanes").mockResolvedValue(true);
    const onCreated = vi.fn();
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onCreated,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();
    const order: string[] = [];
    flush.mockImplementation(async () => {
      order.push("flush");
      return true;
    });
    vi.spyOn(api, "listMutationSetEntries").mockImplementation(async () => {
      order.push("list");
      return { entries: entries() } as MutationSetEntryList;
    });
    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    await tick();
    return { onCreated, order };
  }

  it("flushes every dirty scene before (re-)listing sets", async () => {
    const { order } = await openApplyTab();
    expect(order).toEqual(["flush", "list"]);
  });

  it("a template is copied pinned to the entity, then anchored", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet").mockResolvedValue({
      entry: fullSet({ id: "tmpl-copy" }),
      dropped_rows: [],
    });
    const { onCreated } = await openApplyTab();

    await fireEvent.click(screen.getByRole("button", { name: /Full moon/ }));
    await tick();
    await tick();

    expect(copySpy).toHaveBeenCalledWith("tmpl", "mira");
    expect(onCreated).toHaveBeenCalledWith("tmpl-copy");
  });

  it("a staged set is anchored directly (no copy call)", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet");
    const { onCreated } = await openApplyTab();

    await fireEvent.click(screen.getByRole("button", { name: /Mira's scar/ }));
    await tick();

    expect(copySpy).not.toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalledWith("staged1");
  });

  it("an active set is offered as Copy only, and copying anchors the copy", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet").mockResolvedValue({
      entry: fullSet({ id: "active-copy" }),
      dropped_rows: [],
    });
    const { onCreated } = await openApplyTab();

    const row = screen.getByRole("button", { name: /Mira's tattoo/ });
    expect(row.textContent).toContain("Copy");
    await fireEvent.click(row);
    await tick();
    await tick();

    // No entity re-pin argument — a plain copy of an already-pinned set.
    expect(copySpy).toHaveBeenCalledWith("active1");
    expect(onCreated).toHaveBeenCalledWith("active-copy");
  });

  it("a set from another layer is always copied, never anchored directly", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet").mockResolvedValue({
      entry: fullSet({ id: "layered-copy" }),
      dropped_rows: [],
    });
    const { onCreated } = await openApplyTab();

    const row = screen.getByRole("button", { name: /Series template/ });
    expect(row.textContent).toContain("Copy");
    await fireEvent.click(row);
    await tick();
    await tick();

    expect(copySpy).toHaveBeenCalledWith("layered1", "mira");
    expect(onCreated).toHaveBeenCalledWith("layered-copy");
  });

  it("tells the writer about dropped_rows", async () => {
    vi.spyOn(api, "copyMutationSet").mockResolvedValue({
      entry: fullSet({ id: "tmpl-copy" }),
      dropped_rows: [{ id: "r1", field: "rank", op: "replace", value: "Captain" }],
    });
    const setError = vi.spyOn(editorPanes, "setError").mockImplementation(() => {});
    await openApplyTab();

    await fireEvent.click(screen.getByRole("button", { name: /Full moon/ }));
    await tick();
    await tick();

    expect(setError).toHaveBeenCalledWith(expect.stringContaining("rank"));
  });
});

describe("MutationAuthoringForm — foreign vs native layer for a staged set (review fix, ADR-0095 §10)", () => {
  // The backend stamps EVERY node with its layer id, the open project's own
  // included, so "foreign" must compare against the open project's own layer
  // id, not test for a non-empty `source_layer_id`.
  function setupLayers(): void {
    metadataSchemaLayersStore.set([
      { id: "root", label: "World", folder_path: "", schema_path: "", exists: true },
      { id: "book", label: "Book", folder_path: "", schema_path: "", exists: true },
    ] satisfies MetadataSchemaLayer[]);
  }

  async function openApplyTabWith(entries: MutationSetEntrySummary[]) {
    setupLayers();
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries } as MutationSetEntryList);
    vi.spyOn(editorPanes, "flushDirtyPanes").mockResolvedValue(true);
    const onCreated = vi.fn();
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onCreated,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "Apply a saved set" }));
    await tick();
    await tick();
    return onCreated;
  }

  it("a staged set whose source_layer_id equals the project's own layer id is anchored as itself (no copy)", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet");
    const onCreated = await openApplyTabWith([
      setSummary({
        id: "staged-own",
        title: "Mira's scar",
        state: "staged",
        target_entity: "mira",
        source_layer_id: "book",
      }),
    ]);

    await fireEvent.click(screen.getByRole("button", { name: /Mira's scar/ }));
    await tick();

    expect(copySpy).not.toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalledWith("staged-own");
  });

  it("a staged set whose source_layer_id differs from the project's own layer id is copied", async () => {
    const copySpy = vi.spyOn(api, "copyMutationSet").mockResolvedValue({
      entry: fullSet({ id: "staged-foreign-copy" }),
      dropped_rows: [],
    });
    const onCreated = await openApplyTabWith([
      setSummary({
        id: "staged-foreign",
        title: "Mira's tattoo",
        state: "staged",
        target_entity: "mira",
        source_layer_id: "root",
      }),
    ]);

    await fireEvent.click(screen.getByRole("button", { name: /Mira's tattoo/ }));
    await tick();
    await tick();

    // Already pinned (unlike a template) — copyActive copies as-is, no
    // separate re-pin argument (matches the native "active set" copy path).
    expect(copySpy).toHaveBeenCalledWith("staged-foreign");
    expect(onCreated).toHaveBeenCalledWith("staged-foreign-copy");
  });
});

describe("MutationAuthoringForm — save as a reusable set (ADR-0095 §6)", () => {
  it("creates a template (no target_entity) and surfaces a failure instead of swallowing it", async () => {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      values: {},
    });
    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "createMutationSetEntry").mockImplementation(async (payload) => {
      if (!payload.target_entity) throw new Error("template rejected");
      return fullSet();
    });
    const setError = vi.spyOn(editorPanes, "setError").mockImplementation(() => {});
    const onCreated = vi.fn();

    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: SCHEMA,
        presetEntityId: "mira",
        sceneId: "scene1",
        onCreated,
        onCancel: NOOP,
      },
    });
    await tick();
    await tick();

    await fireEvent.click(screen.getByRole("button", { name: "Add field change" }));
    await fireEvent.input(screen.getByLabelText("Title (name)"), { target: { value: "The Wolf" } });
    await fireEvent.click(screen.getByLabelText(/Save as a reusable set/));
    await fireEvent.click(screen.getByRole("button", { name: "Insert mutation" }));
    await tick();
    await tick();
    await tick();

    // The primary create still succeeds and the anchor still lands.
    expect(onCreated).toHaveBeenCalledWith("set1");
    // But the template failure is surfaced, not swallowed.
    expect(setError).toHaveBeenCalledWith(expect.stringContaining("template rejected"));
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

  function renderKeyedSet() {
    vi.spyOn(api, "getEntityEffectiveState").mockResolvedValue({
      entity_id: "mira",
      scene_id: "scene1",
      position: null,
      // The baseline EXCLUDES this pill's own anchor — the server-side
      // `exclude` contract (#71, ADR-0017 for the collection case; the same
      // fetch serves the item-edit baseline).
      values: {
        relationships: [
          { to: "lore_c", active: true },
          { to: "lore_d", active: true },
        ],
      },
    });
    const onSaved = vi.fn();
    render(MutationAuthoringForm, {
      props: {
        loreEntries: [lore("mira", "Mira")],
        schema: KEYED_SCHEMA,
        sceneId: "scene1",
        initial: fullSet({
          rows: [
            { id: "rec_add_a", field: "relationships", op: "add", value: encodeItem({ to: "lore_a", active: true }) },
            { id: "rec_replace_c", field: "relationships.lore_c.active", op: "replace", value: "false" },
          ],
        }),
        anchorId: "a1",
        onSaved,
        onCancel: NOOP,
      },
    });
    return onSaved;
  }

  it("seeds the keyed field from the composed effective items — the baseline plus this set's own prior rows", async () => {
    renderKeyedSet();
    await tick();
    await tick();

    // lore_c and lore_d come from the baseline; lore_a from this set's own
    // prior `add` row — all three visible without any interaction.
    expect(screen.getByText("lore_c")).toBeInTheDocument();
    expect(screen.getByText("lore_d")).toBeInTheDocument();
    expect(screen.getByText("lore_a")).toBeInTheDocument();
  });

  it("saves with add/replace/remove rows, preserved ids", async () => {
    const saveSpy = vi.spyOn(api, "saveMutationSetEntry").mockResolvedValue(fullSet());
    renderKeyedSet();
    await tick();
    await tick();

    // Remove the baseline item lore_d (items render in composed order:
    // lore_c, lore_d, lore_a).
    const removeButtons = screen.getAllByRole("button", { name: "Remove item" });
    await fireEvent.click(removeButtons[1]);

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await tick();

    expect(saveSpy).toHaveBeenCalledTimes(1);
    const saved = saveSpy.mock.calls[0][0];
    expect(saved.rows).toEqual(
      expect.arrayContaining([
        // The add is unchanged — reuses its existing id.
        { id: "rec_add_a", field: "relationships", op: "add", value: encodeItem({ to: "lore_a", active: true }) },
        // The replace re-derives from raw baseline vs the composed value —
        // still differs (true → false), so it's re-emitted, reusing its id.
        { id: "rec_replace_c", field: "relationships.lore_c.active", op: "replace", value: "false" },
        // A fresh remove for the baseline item just deleted — no prior id.
        { id: "", field: "relationships", op: "remove", value: "lore_d" },
      ]),
    );
    expect(saved.rows).toHaveLength(3);
  });
});
