// @vitest-environment happy-dom
// Field inline-editor UI fixes (0.9.5 dogfooding batch):
//   #999  the display-name placeholder is a generic hint, not a specific example.
//   #1000 the L1 grouping control is labelled "Section" (not "Group", which
//         collided with reusable L2 groups) and doubles as a pick-from-existing
//         dropdown via a datalist of the labels already used on the type.
//   #1001 the icon popover dismisses on `click`, not `mousedown`, so a press on
//         a scrollbar gutter no longer closes it mid-scroll.
//   #1003 the `list` item-shape dropdown hides built-in `system` groups, but
//         still shows one a field already uses so its shape stays valid.
//   #1004 the editor carries an author `description`, threaded through the
//         saved draft and seeded back when editing an existing field.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { MetadataFieldDefinition, MetadataGroupDefinition } from "@/lib/types";
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

  it("#1573: the icon popover is body-portaled so the pane's overflow can't clip it", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("Choose icon"));
    const pop = document.querySelector(".sfi-icon-pop");
    expect(pop).not.toBeNull();
    // Reparented out of the editor and straight under <body> (#1573) — a click
    // inside it (selecting an icon) must therefore still count as "inside".
    expect(pop!.parentElement).toBe(document.body);
    await fireEvent.click(pop!.querySelector(".ip-search") as HTMLElement);
    expect(screen.queryByRole("dialog")).toBeTruthy();
  });

  it("ADR-0082 slice 2b: the field-type picker no longer offers 'Tags'", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("Change field type"));
    const options = screen.queryAllByRole("option", { name: "Tags" });
    expect(options).toHaveLength(0);
    // The sibling ref-list type is still there — a tag vocabulary is authored
    // through it (entity_ref_list → source kind "tag" → create_missing).
    expect(screen.getByRole("option", { name: "Entry Reference, Multiple" })).toBeInTheDocument();
  });
});

const GROUPS: Record<string, MetadataGroupDefinition> = {
  gmo: { name: "GMO", members: [{ key: "goal", name: "Goal", type: "text" }] },
  // A ref-member group — a valid item shape as of ADR-0081 (a nested ref is
  // tracked wherever it lives), so it must be OFFERED.
  cast: { name: "Cast", members: [{ key: "who", name: "Who", type: "entity_ref" }] },
  // An entity_ref_list-member group — valid as of ADR-0081 slice 3 (the ref
  // lifecycle descends into a list member too), so it too must be OFFERED.
  topics: { name: "Topics", members: [{ key: "topic", name: "Topic", type: "entity_ref_list" }] },
  // A built-in machinery group — must not be offered as a new item shape.
  plot_beat_link: {
    name: "Beat link",
    system: true,
    members: [{ key: "plotline", name: "Plotline", type: "text" }],
  },
};

function mountList(field: MetadataFieldDefinition) {
  render(SchemaFieldInlineEditor, {
    props: {
      field,
      selectedFieldId: "beats",
      layerId: "proj",
      groups: GROUPS,
      onSave: vi.fn(),
      onCancel: vi.fn(),
      onRemove: vi.fn(),
    },
  });
}

function itemShapeValues(): { values: string[]; disabled: Map<string, boolean> } {
  const select = screen.getByLabelText("List item shape") as HTMLSelectElement;
  const options = [...select.querySelectorAll("option")] as HTMLOptionElement[];
  return {
    values: options.map((o) => o.value),
    disabled: new Map(options.map((o) => [o.value, o.disabled])),
  };
}

describe("SchemaFieldInlineEditor list item shape hides system groups (#1003)", () => {
  it("does not offer a system group as a new item shape", () => {
    mountList({ name: "Beats", type: "list", options: [] });
    const { values } = itemShapeValues();
    expect(values).toContain("group:gmo");
    expect(values).not.toContain("group:plot_beat_link");
  });

  it("offers a group with an entity_ref member as an item shape (ADR-0081)", () => {
    mountList({ name: "Beats", type: "list", options: [] });
    const { values } = itemShapeValues();
    expect(values).toContain("group:cast"); // ref-member group is now shapeable
  });

  it("offers a group with an entity_ref_list member as an item shape (ADR-0081 slice 3)", () => {
    mountList({ name: "Beats", type: "list", options: [] });
    const { values } = itemShapeValues();
    expect(values).toContain("group:topics"); // entity_ref_list-member group is now shapeable
  });

  it("still shows a system group the field already uses, as a valid (not disabled) shape", () => {
    mountList({ name: "Beats", type: "list", item_group: "plot_beat_link", options: [] });
    const { values, disabled } = itemShapeValues();
    expect(values).toContain("group:plot_beat_link");
    // It's a real, resolvable shape — not the disabled "current shape missing" fallback.
    expect(disabled.get("group:plot_beat_link")).toBe(false);
  });
});

function mountComputed(field: MetadataFieldDefinition, onSave = vi.fn()) {
  render(SchemaFieldInlineEditor, {
    props: {
      field,
      selectedFieldId: "fld",
      layerId: "proj",
      onSave,
      onCancel: vi.fn(),
      onRemove: vi.fn(),
    },
  });
  return onSave;
}

function optionValues(labelText: string): string[] {
  const select = screen.getByLabelText(labelText) as HTMLSelectElement;
  return [...select.querySelectorAll("option")].map((o) => (o as HTMLOptionElement).value);
}

describe("SchemaFieldInlineEditor computed cost function (#353)", () => {
  it("round-trips an existing cost field instead of coercing it to word_count", async () => {
    const onSave = mountComputed({
      name: "AI cost",
      type: "computed",
      options: [],
      computed: { function: "cost", scope: "scene" },
    });
    // The bug: opening a cost field and saving it rewrote it as word_count.
    await fireEvent.click(screen.getByText("Done"));
    expect(onSave).toHaveBeenCalledOnce();
    const payload = onSave.mock.calls[0][0];
    expect(payload.computedFunction).toBe("cost");
    expect(payload.computedScope).toBe("scene");
  });

  it("offers cost in the Computation select and shows its own scopes", () => {
    mountComputed({
      name: "AI cost",
      type: "computed",
      options: [],
      computed: { function: "cost", scope: "character" },
    });
    expect(optionValues("Computation")).toContain("cost");
    const scope = screen.getByLabelText("Scope") as HTMLSelectElement;
    expect(scope.value).toBe("character");
    expect(optionValues("Scope")).toEqual(["scene", "character", "project"]);
  });

  it("resets scope to the new function's default when the old scope doesn't fit", async () => {
    const onSave = mountComputed({
      name: "Number",
      type: "computed",
      options: [],
      computed: { function: "counter", scope: "manuscript" },
    });
    // counter's `manuscript` is not a cost scope, so switching to cost must
    // reset it to cost's default (scene) rather than carry an invalid scope.
    await fireEvent.change(screen.getByLabelText("Computation"), { target: { value: "cost" } });
    await fireEvent.click(screen.getByText("Done"));
    const payload = onSave.mock.calls[0][0];
    expect(payload.computedFunction).toBe("cost");
    expect(payload.computedScope).toBe("scene");
  });

  it("hides the Scope control and clears the scope for word_count", async () => {
    const onSave = mountComputed({
      name: "Words",
      type: "computed",
      options: [],
      computed: { function: "counter", scope: "siblings" },
    });
    await fireEvent.change(screen.getByLabelText("Computation"), { target: { value: "word_count" } });
    expect(screen.queryByLabelText("Scope")).toBeNull();
    await fireEvent.click(screen.getByText("Done"));
    expect(onSave.mock.calls[0][0].computedScope).toBe("");
  });

  it("preserves a stored function it doesn't recognize rather than coercing it", async () => {
    const onSave = mountComputed({
      name: "Future",
      type: "computed",
      options: [],
      computed: { function: "future_fn", scope: "whatever" },
    });
    expect((screen.getByLabelText("Computation") as HTMLSelectElement).value).toBe("future_fn");
    // No scope control for an unknown function, but its stored scope survives.
    expect(screen.queryByLabelText("Scope")).toBeNull();
    await fireEvent.click(screen.getByText("Done"));
    const payload = onSave.mock.calls[0][0];
    expect(payload.computedFunction).toBe("future_fn");
    expect(payload.computedScope).toBe("whatever");
  });
});

describe("SchemaFieldInlineEditor author description (#1004)", () => {
  it("threads a typed description through the saved draft", async () => {
    const onSave = vi.fn();
    render(SchemaFieldInlineEditor, {
      props: { field: null, selectedFieldId: null, layerId: "proj", onSave, onCancel: vi.fn(), onRemove: vi.fn() },
    });
    await fireEvent.input(screen.getByLabelText("Field display name"), { target: { value: "Bio" } });
    await fireEvent.input(screen.getByLabelText("Field description"), {
      target: { value: "The character's backstory in brief." },
    });
    await fireEvent.click(screen.getByText("Done"));
    expect(onSave).toHaveBeenCalledOnce();
    expect(onSave.mock.calls[0][0].description).toBe("The character's backstory in brief.");
  });

  it("seeds the description input from an existing field", () => {
    render(SchemaFieldInlineEditor, {
      props: {
        field: { name: "Bio", type: "long_text", options: [], description: "Existing help." },
        selectedFieldId: "bio",
        layerId: "proj",
        onSave: vi.fn(),
        onCancel: vi.fn(),
        onRemove: vi.fn(),
      },
    });
    expect((screen.getByLabelText("Field description") as HTMLTextAreaElement).value).toBe("Existing help.");
  });
});

describe("SchemaFieldInlineEditor AI-authorship toggle (ADR-0059)", () => {
  it("defaults to AI-writable and threads that through the saved draft", async () => {
    const onSave = vi.fn();
    render(SchemaFieldInlineEditor, {
      props: { field: null, selectedFieldId: null, layerId: "proj", onSave, onCancel: vi.fn(), onRemove: vi.fn() },
    });
    const toggle = screen.getByLabelText("AI may write this field");
    expect(toggle.getAttribute("aria-checked")).toBe("true"); // §E default: writable unless opted out
    await fireEvent.input(screen.getByLabelText("Field display name"), { target: { value: "Bio" } });
    await fireEvent.click(screen.getByText("Done"));
    expect(onSave.mock.calls[0][0].aiProposable).toBe(true);
  });

  it("threads an opt-out (toggle off) through the saved draft", async () => {
    const onSave = vi.fn();
    render(SchemaFieldInlineEditor, {
      props: { field: null, selectedFieldId: null, layerId: "proj", onSave, onCancel: vi.fn(), onRemove: vi.fn() },
    });
    await fireEvent.input(screen.getByLabelText("Field display name"), { target: { value: "Notes" } });
    await fireEvent.click(screen.getByLabelText("AI may write this field")); // toggle off
    await fireEvent.click(screen.getByText("Done"));
    expect(onSave.mock.calls[0][0].aiProposable).toBe(false);
  });

  it("seeds the toggle from an existing off-limits field", () => {
    render(SchemaFieldInlineEditor, {
      props: {
        field: { name: "Context policy", type: "select", options: [], ai_proposable: false },
        selectedFieldId: "context_policy",
        layerId: "proj",
        onSave: vi.fn(),
        onCancel: vi.fn(),
        onRemove: vi.fn(),
      },
    });
    expect(screen.getByLabelText("AI may write this field").getAttribute("aria-checked")).toBe("false");
  });

  it("hides the toggle for a never-proposable type (computed)", () => {
    render(SchemaFieldInlineEditor, {
      props: {
        field: { name: "Word count", type: "computed", options: [] },
        selectedFieldId: "word_count",
        layerId: "proj",
        onSave: vi.fn(),
        onCancel: vi.fn(),
        onRemove: vi.fn(),
      },
    });
    // Computed/reference fields are never AI-proposed regardless of the flag,
    // so the control is not shown (it would be an inert switch).
    expect(screen.queryByLabelText("AI may write this field")).toBeNull();
  });
});
