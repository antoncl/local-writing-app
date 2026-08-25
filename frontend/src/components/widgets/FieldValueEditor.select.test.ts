// @vitest-environment happy-dom
// Required-select behavior (#1421): a select whose schema declares a `default` is
// "required" — it drops the "(none)" pick and shows the default when the stored
// value is absent. A select with no default stays optional (blank allowed).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

const selectField = (extra: Partial<MetadataFieldDefinition> = {}): MetadataFieldDefinition =>
  ({
    name: "Context policy",
    type: "select",
    options: [
      { value: "always", label: "Always include" },
      { value: "auto", label: "Automatic (alias match)" },
      { value: "never", label: "Never include" },
    ],
    ...extra,
  }) as MetadataFieldDefinition;

const mount = (field: MetadataFieldDefinition, value: MetadataValue) => {
  const onChange = vi.fn();
  render(FieldValueEditor, { props: { field, value, onChange } });
  return { onChange };
};

describe("FieldValueEditor — required select (#1421)", () => {
  it("displays the default when the stored value is absent", () => {
    mount(selectField({ default: "auto" }), "");
    // The trigger shows the default option's label, not the "(none)" placeholder.
    expect(screen.getByText("Automatic (alias match)")).toBeTruthy();
    expect(screen.queryByText("(none)")).toBeNull();
  });

  it("offers no blank row (only the real options)", async () => {
    mount(selectField({ default: "auto" }), "");
    await fireEvent.click(screen.getByRole("button")); // open the popover
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.queryByText("(none)")).toBeNull();
  });

  it("keeps the blank pick for an optional select (no default)", async () => {
    mount(selectField(), "");
    await fireEvent.click(screen.getByRole("button"));
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(4); // 3 options + the leading "(none)" blank row
    expect(options[0].textContent).toContain("(none)");
  });

  it("shows an explicit value in preference to the default", () => {
    mount(selectField({ default: "auto" }), "always");
    expect(screen.getByText("Always include")).toBeTruthy();
  });
});
