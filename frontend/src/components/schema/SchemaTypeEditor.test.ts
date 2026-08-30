// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
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
  it("renders the icon tile in the identity header, seeded from initialIcon", () => {
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

  it("portals the icon popover to <body> so a short pane can't clip it (#1573)", async () => {
    render(SchemaTypeEditor, {
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
    await fireEvent.click(screen.getByRole("button", { name: "Choose icon" }));
    // The popover is lifted out of the pane's overflow box and reparented under
    // <body> — the whole point of #1573. (Position maths are layout-driven, not
    // asserted under happy-dom; the reparent is what defeats the clip.)
    const pop = document.querySelector(".sti-icon-pop");
    expect(pop).not.toBeNull();
    expect(pop!.parentElement).toBe(document.body);
    expect(pop!.querySelector(".icon-picker")).not.toBeNull();
  });
});

describe("SchemaTypeEditor identity header (#1656)", () => {
  // Colour + icon ARE the type's identity, so they sit in the identity header
  // beside the name (its avatar) — not as standalone body rows below.
  it("places the icon tile and colour swatch beside the name, not as body rows", () => {
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
    const header = container.querySelector(".schema-type-identity-header");
    expect(header).not.toBeNull();
    // The icon tile, the colour swatch, and the name input all share the header.
    expect(header!.querySelector(".sti-icon-btn")).not.toBeNull();
    expect(header!.querySelector(".swatch-trigger")).not.toBeNull();
    expect(header!.querySelector(".stn-input")).not.toBeNull();
    // The old standalone Color / Icon rows are gone.
    expect(container.querySelector(".schema-type-color-row")).toBeNull();
    expect(container.querySelector(".schema-type-icon-row")).toBeNull();
  });
});

describe("SchemaTypeEditor built-in color/icon are overridable (#1644)", () => {
  // #1574 made Color + Icon read-only on a built-in because Save Type was gated
  // off. #1644 reverses that: the display overlay (color + icon) persists as a
  // project-layer override, so the controls are editable and Save is available —
  // while name / id stay locked (identity is system-owned, stripped on write).
  const builtinProps = {
    schemaTypeKind: "lore" as const,
    initialName: "Character",
    initialTypeId: "lore:character",
    selectedSchemaTypeId: "lore:character",
    schemaTypeLayerId: "proj",
    schemaTypeReadonly: true,
  };

  it("keeps the Color swatch editable on a readonly (built-in) type", () => {
    const { container } = render(SchemaTypeEditor, {
      props: { ...builtinProps, initialColor: "blue", onSaveType: vi.fn() },
    });
    const swatch = container.querySelector(".swatch-trigger") as HTMLButtonElement | null;
    expect(swatch).not.toBeNull();
    expect(swatch!.disabled).toBe(false);
    expect(swatch!.classList.contains("read-only")).toBe(false);
  });

  it("lets the Icon tile open the picker on a readonly type, and offers Save", async () => {
    const { container } = render(SchemaTypeEditor, {
      props: { ...builtinProps, initialIcon: "user", onSaveType: vi.fn() },
    });
    // Editable: labelled "Choose icon", not disabled, shows the seeded glyph...
    const tile = screen.getByRole("button", { name: "Choose icon" }) as HTMLButtonElement;
    expect(tile.disabled).toBe(false);
    expect(tile.classList.contains("read-only")).toBe(false);
    expect(container.querySelector(".sti-icon-btn .ti-user")).not.toBeNull();
    // ...and clicking opens the picker (the #1574 dead end is gone).
    await fireEvent.click(tile);
    expect(document.querySelector(".sti-icon-pop")).not.toBeNull();
    expect(document.querySelector(".icon-picker")).not.toBeNull();
    // Save Type renders so the color/icon overlay can persist.
    expect(screen.getByRole("button", { name: "Save Type" })).toBeTruthy();
  });

  it("keeps the type name read-only — identity stays system-owned", () => {
    render(SchemaTypeEditor, { props: { ...builtinProps, onSaveType: vi.fn() } });
    const nameInput = screen.getByPlaceholderText("Enter type name…") as HTMLInputElement;
    expect(nameInput.readOnly).toBe(true);
    // The scope line names where the overlay lands, not a dead "System".
    expect(screen.getByText(/color and icon save to your project/i)).toBeTruthy();
  });
});
