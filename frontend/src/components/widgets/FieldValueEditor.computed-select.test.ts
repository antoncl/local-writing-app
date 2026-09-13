// @vitest-environment happy-dom
// #1928: a computed `select` (value_type "select") with options — the `layer`
// field — must render in the view designer's Filter as an options PICKER, not a
// free-form text box. The field reaches FieldValueEditor via `toMultiValued`,
// which widens a computed select WITH options to `multi_select` (→ chips) but
// leaves an options-less one typed `computed` (→ the fall-through text input).
// This pins BOTH ends: the empty-options render is exactly the symptom seen when
// read_metadata_schema_overview shipped `layer` with no options (fixed backend-
// side); the with-options render is what the fix restores.
import { describe, it, expect } from "vitest";
import { render, screen } from "@/lib/test/component";
import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
import { toMultiValued } from "@/lib/views/viewParams";
import type { MetadataFieldDefinition } from "@/lib/types";

const computedSelect = (options: { value: string; label?: string }[]): MetadataFieldDefinition =>
  ({
    name: "Layer",
    type: "computed",
    category: "computed",
    computed: { value_type: "select" },
    options,
  }) as unknown as MetadataFieldDefinition;

describe("FieldValueEditor — computed select Filter widget (#1928)", () => {
  it("renders an options picker (chips), not a text box, when options are present", () => {
    render(FieldValueEditor, {
      props: {
        field: toMultiValued(computedSelect([
          { value: "lib", label: "Library" },
          { value: "book", label: "Book" },
        ])),
        value: null,
        onChange: () => {},
        pickDerived: true,
      },
    });
    expect(screen.getByText("Library")).toBeTruthy();
    expect(screen.getByText("Book")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("falls through to a text box when the computed select has EMPTY options (the pre-fix symptom)", () => {
    render(FieldValueEditor, {
      props: { field: toMultiValued(computedSelect([])), value: null, onChange: () => {}, pickDerived: true },
    });
    expect(screen.getByRole("textbox")).toBeTruthy();
  });
});
