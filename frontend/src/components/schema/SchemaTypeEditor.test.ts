// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import SchemaTypeEditor from "./SchemaTypeEditor.svelte";

describe("SchemaTypeEditor reusable groups on built-in types (#1033)", () => {
  it("shows Add group and the Reusable-groups section on a readonly (built-in) type", () => {
    // Regression: the affordances were gated `{#if !schemaTypeReadonly}`, so a
    // built-in type like lore:character — where "Add field" already works —
    // could not attach a reusable group, even though the backend accepts group
    // applications as per-layer overlays on built-ins (ADR-0029 §A,
    // set_entry_type_group_applications has "No built-in guard").
    render(SchemaTypeEditor, {
      props: {
        schemaTypeKind: "lore" as const,
        initialName: "Character",
        initialTypeId: "lore:character",
        selectedSchemaTypeId: "lore:character",
        schemaTypeLayerId: "proj",
        schemaTypeReadonly: true,
        onSaveType: vi.fn(),
      },
    });
    // Both formerly-gated affordances render: the peer "Add group" button and
    // the Reusable-groups section's "Manage…" link.
    expect(screen.getByRole("button", { name: "Add group" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Manage…" })).toBeTruthy();
  });
});

describe("SchemaTypeEditor type icon (#316)", () => {
  it("renders the Icon row with a choose-icon tile, seeded from initialIcon", () => {
    const { container } = render(SchemaTypeEditor, {
      props: {
        schemaTypeKind: "lore" as const,
        initialName: "Character",
        initialTypeId: "lore:character",
        initialIcon: "user",
        selectedSchemaTypeId: "lore:character",
        schemaTypeLayerId: "proj",
        onSaveType: vi.fn(),
      },
    });
    // The tile toggles the shared IconPicker (mirrors the field-icon gesture)...
    const tile = screen.getByRole("button", { name: "Choose icon" });
    expect(tile).toBeTruthy();
    // ...and shows the seeded own-icon glyph (solid, not the dashed inherit state).
    expect(container.querySelector(".sti-icon-btn .ti-user")).not.toBeNull();
    expect(tile.classList.contains("inheriting")).toBe(false);
  });
});
