// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import SchemaTypeCreateForm from "./SchemaTypeCreateForm.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema, MetadataSchemaLayer } from "@/lib/types";

// Minimal lore schema: a kind root (lore:base) + one concrete type (lore:character).
const SCHEMA = {
  entry_types: {
    "lore:base": { kind: "lore", name: "Lore Entries", parent: null, abstract: true, fields: [] },
    "lore:character": { kind: "lore", name: "Character", parent: "lore:base", fields: [] },
  },
  fields: {},
  groups: {},
} as unknown as MetadataSchema;

const ONE_LAYER = [{ id: "proj", label: "Project" }] as unknown as MetadataSchemaLayer[];
const TWO_LAYERS = [
  { id: "proj", label: "Project" },
  { id: "series", label: "Series" },
] as unknown as MetadataSchemaLayer[];

beforeEach(() => metadataSchemaStore.set(SCHEMA));
afterEach(() => metadataSchemaStore.set(null));

function renderForm(overrides = {}) {
  return render(SchemaTypeCreateForm, {
    props: {
      kind: "lore" as const,
      seedParentId: "lore:base",
      kindRootId: "lore:base",
      layers: ONE_LAYER,
      defaultLayerId: "proj",
      onSubmit: vi.fn(),
      onCancel: vi.fn(),
      ...overrides,
    },
  });
}

describe("SchemaTypeCreateForm (#1659)", () => {
  it("titles 'New type' at the kind root and uses a neutral name placeholder", () => {
    renderForm();
    expect(screen.getByText("New type")).toBeTruthy();
    // Neutral ghost text — not an example that reads as a default (#1659).
    expect(screen.getByPlaceholderText("Enter type name…")).toBeTruthy();
  });

  it("titles 'New sub-type' when it extends a non-root type", () => {
    renderForm({ seedParentId: "lore:character" });
    expect(screen.getByText("New sub-type")).toBeTruthy();
  });

  it("previews the id live from the name — top-level under the kind root", async () => {
    renderForm();
    await fireEvent.input(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Faction" } });
    // Kind root ⇒ no nesting: lore:faction.
    expect(screen.getByText("lore:faction")).toBeTruthy();
  });

  it("previews a nested id under a non-root parent", async () => {
    renderForm({ seedParentId: "lore:character" });
    await fireEvent.input(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Elite" } });
    // Nested under the parent's local key: lore:character:elite.
    expect(screen.getByText("lore:character:elite")).toBeTruthy();
  });

  it("disables Create until the name yields a usable id, then emits the payload", async () => {
    const onSubmit = vi.fn();
    renderForm({ onSubmit });
    const create = screen.getByRole("button", { name: "Create" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    // Whitespace / unsluggable input keeps it disabled.
    await fireEvent.input(screen.getByRole("textbox", { name: "Name" }), { target: { value: "   " } });
    expect(create.disabled).toBe(true);
    await fireEvent.input(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Faction" } });
    expect(create.disabled).toBe(false);
    await fireEvent.click(create);
    // localKey is what the card previewed, so preview == saved.
    expect(onSubmit).toHaveBeenCalledWith({ name: "Faction", parentId: "lore:base", layerId: "proj", localKey: "faction" });
  });

  it("shows the Save-layer picker only when the project has more than one layer", () => {
    const { unmount } = renderForm({ layers: ONE_LAYER });
    expect(screen.queryByRole("combobox", { name: "Save layer" })).toBeNull();
    unmount();
    renderForm({ layers: TWO_LAYERS });
    expect(screen.getByRole("combobox", { name: "Save layer" })).toBeTruthy();
  });

  it("cancels on Cancel", async () => {
    const onCancel = vi.fn();
    renderForm({ onCancel });
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
