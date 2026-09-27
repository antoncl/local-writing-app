// The Remove dialog for a type's field (#2280): remove-from-this-type by
// default, delete-everywhere behind a checkbox, and delete-only when the type
// can't drop the field on its own.
import { describe, expect, it } from "vitest";
import type { FieldRemovalPreview } from "@/lib/types";
import { fieldRemovalDialog } from "./fieldRemovalDialog";

const names: Record<string, string> = {
  "lore:character": "Character",
  "lore:character:main_character": "Main character",
  "lore:character:sidekick": "Sidekick",
  "lore:character:mentor": "Mentor",
};
const typeName = (id: string) => names[id] ?? id;

function preview(overrides: Partial<FieldRemovalPreview> = {}): FieldRemovalPreview {
  return {
    entry_type_id: "lore:character:main_character",
    field_id: "truth",
    blocked_by: null,
    inherited_from: null,
    listings: [{ layer_id: "book", layer_label: "Book", shared: false }],
    subtypes_losing: [],
    other_types: [],
    ...overrides,
  };
}

describe("fieldRemovalDialog", () => {
  it("removes from this type by default, with delete-everywhere as the option", () => {
    const dialog = fieldRemovalDialog(preview({ other_types: ["lore:character:sidekick"] }), "Truth", typeName);

    expect(dialog.deleteOnly).toBe(false);
    expect(dialog.confirmLabel).toBe("Remove from type");
    expect(dialog.message).toContain('Remove "Truth" from Main character?');
    expect(dialog.message).toContain("stays defined and on its other types");
    expect(dialog.option?.label).toContain("also from Sidekick");
    expect(dialog.option?.confirmLabel).toBe("Delete everywhere");
    expect(dialog.details).toEqual([]);
  });

  it("warns when a listing lives in a shared higher layer, and names subtypes that lose it", () => {
    const dialog = fieldRemovalDialog(
      preview({
        listings: [
          { layer_id: "aetheria", layer_label: "Aetheria", shared: true },
          { layer_id: "book", layer_label: "Book", shared: false },
        ],
        subtypes_losing: ["lore:character:mentor"],
      }),
      "Truth",
      typeName,
    );

    expect(dialog.details).toEqual([
      "Listed at Aetheria: every project that inherits Aetheria loses it on Main character too.",
      "Also removed from Mentor, which get it only through Main character.",
    ]);
  });

  it("offers only delete-everywhere when the parent type supplies the field", () => {
    const dialog = fieldRemovalDialog(
      preview({ blocked_by: "parent", inherited_from: "lore:character", listings: [] }),
      "Truth",
      typeName,
    );

    expect(dialog.deleteOnly).toBe(true);
    expect(dialog.option).toBeUndefined();
    expect(dialog.confirmLabel).toBe("Delete everywhere");
    expect(dialog.message).toContain("from its parent type Character");
  });
});
