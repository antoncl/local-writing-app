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

describe("SchemaTypeEditor built-in appearance is read-only (#1574)", () => {
  // Save Type is gated `{#if !schemaTypeReadonly}`, so on a built-in type the
  // Color + Icon pickers looked editable but had no way to persist — a silent
  // dead end. They now render read-only: the appearance is still visible, but
  // the controls don't invite an edit that can't be saved.
  it("disables the Color swatch on a readonly (built-in) type", () => {
    const { container } = render(SchemaTypeEditor, {
      props: {
        schemaTypeKind: "lore" as const,
        initialName: "Character",
        initialTypeId: "lore:character",
        initialColor: "blue",
        selectedSchemaTypeId: "lore:character",
        schemaTypeLayerId: "proj",
        schemaTypeReadonly: true,
        onSaveType: vi.fn(),
      },
    });
    const swatch = container.querySelector(".swatch-trigger") as HTMLButtonElement | null;
    expect(swatch).not.toBeNull();
    expect(swatch!.disabled).toBe(true);
    expect(swatch!.classList.contains("read-only")).toBe(true);
  });

  it("makes the Icon tile a non-opening display on a readonly type", async () => {
    const { container } = render(SchemaTypeEditor, {
      props: {
        schemaTypeKind: "lore" as const,
        initialName: "Character",
        initialTypeId: "lore:character",
        initialIcon: "user",
        selectedSchemaTypeId: "lore:character",
        schemaTypeLayerId: "proj",
        schemaTypeReadonly: true,
        onSaveType: vi.fn(),
      },
    });
    // Relabelled from "Choose icon" — it no longer offers a choice — and disabled.
    const tile = screen.getByRole("button", { name: "Icon" }) as HTMLButtonElement;
    expect(tile.disabled).toBe(true);
    expect(tile.classList.contains("read-only")).toBe(true);
    // Still shows the built-in's glyph, so the appearance stays visible.
    expect(container.querySelector(".sti-icon-btn .ti-user")).not.toBeNull();
    // Clicking cannot open the picker (the dead end #1574 removes).
    await fireEvent.click(tile);
    expect(document.querySelector(".sti-icon-pop")).toBeNull();
    expect(document.querySelector(".icon-picker")).toBeNull();
  });
});
