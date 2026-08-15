// @vitest-environment happy-dom
// Field inline-editor UI fixes (0.9.5 dogfooding batch):
//   #999  the display-name placeholder is a generic hint, not a specific example.
//   #1000 the L1 grouping control is labelled "Section" (not "Group", which
//         collided with reusable L2 groups) and doubles as a pick-from-existing
//         dropdown via a datalist of the labels already used on the type.
//   #1001 the icon popover dismisses on `click`, not `mousedown`, so a press on
//         a scrollbar gutter no longer closes it mid-scroll.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import SchemaFieldInlineEditor from "./SchemaFieldInlineEditor.svelte";

function mount(sectionLabels: string[] = []) {
  render(SchemaFieldInlineEditor, {
    props: {
      field: null,
      selectedFieldId: null,
      layerId: "proj",
      sectionLabels,
      onSave: vi.fn(),
      onCancel: vi.fn(),
      onRemove: vi.fn(),
    },
  });
}

describe("SchemaFieldInlineEditor field-editor fixes", () => {
  it("#999: the display-name placeholder is a generic hint", () => {
    mount();
    const name = screen.getByLabelText("Field display name") as HTMLInputElement;
    expect(name.placeholder).toBe("Field name");
    // Guard against the old product-specific example creeping back.
    expect(name.placeholder).not.toMatch(/POV/i);
  });

  it("#1000: the L1 grouping control is labelled 'Section', not 'Group'", () => {
    mount();
    expect(screen.getByLabelText("Section")).toBeTruthy();
    expect(screen.queryByLabelText("Group section")).toBeNull();
  });

  it("#1000: the Section input offers the type's existing labels, deduped and trimmed", () => {
    mount(["Identity", "Identity", "  ", "Status"]);
    const section = screen.getByLabelText("Section") as HTMLInputElement;
    const listId = section.getAttribute("list");
    expect(listId).toBeTruthy();
    const datalist = document.getElementById(listId as string);
    const values = [...(datalist?.querySelectorAll("option") ?? [])].map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(["Identity", "Status"]);
  });

  it("#1001: the icon popover closes on an outside click but survives an outside mousedown", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("Choose icon"));
    expect(screen.queryByRole("dialog")).toBeTruthy();

    // A press on a scrollbar fires mousedown but no click — it must NOT dismiss.
    await fireEvent.mouseDown(screen.getByLabelText("Field display name"));
    expect(screen.queryByRole("dialog")).toBeTruthy();

    // A genuine outside click does dismiss.
    await fireEvent.click(screen.getByLabelText("Field display name"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
