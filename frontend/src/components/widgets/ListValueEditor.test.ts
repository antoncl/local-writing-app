// @vitest-environment happy-dom
// ListValueEditor (#698, ADR-0048 §6): the one row-based add/remove/reorder
// widget for `list` fields. Fixtures avoid long_text members — that density
// hosts TipTap (MetadataLongTextEditor), which the harness deliberately does
// not mount (#642); the long_text row is covered by the real-browser pass.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ListValueEditor from "@/components/widgets/ListValueEditor.svelte";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

const recordField: MetadataFieldDefinition = {
  name: "Open questions",
  type: "list",
  options: [],
  item_group: "open_question",
  item_scalar: false,
  item_members: [
    { key: "question", name: "Question", type: "text" },
    {
      key: "status",
      name: "Status",
      type: "select",
      options: [{ value: "open" }, { value: "answered" }],
    },
  ],
};

const scalarField: MetadataFieldDefinition = {
  name: "Aliases",
  type: "list",
  options: [],
  item_type: "text",
  item_scalar: true,
  item_members: [{ key: "value", name: "Aliases", type: "text" }],
};

const recordItems: MetadataValue = [
  { question: "Who forged the letter?", status: "open" },
  { question: "Where is the key?", status: "answered" },
];

describe("ListValueEditor — record shape (group items)", () => {
  it("renders one collapsed row per item: title member + summary trail", () => {
    render(ListValueEditor, { field: recordField, value: recordItems, onChange: () => {} });
    expect(screen.getByText("Who forged the letter?")).toBeInTheDocument();
    expect(screen.getByText("Where is the key?")).toBeInTheDocument();
    // The non-title member's value rides the muted trail.
    expect(screen.getByText("open")).toBeInTheDocument();
  });

  it("expands one row in place — the header stays, no Done button", async () => {
    render(ListValueEditor, { field: recordField, value: recordItems, onChange: () => {} });
    await fireEvent.click(screen.getByText("Who forged the letter?"));
    // Member editors are live (text input carries the member value).
    expect(screen.getByDisplayValue("Who forged the letter?")).toBeInTheDocument();
    // The header is still present (click-again-to-collapse), and nothing
    // renders a Done affordance — values land as typed (the mockup decision).
    expect(screen.getByText("Who forged the letter?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    // Opening a second row closes the first (one at a time).
    await fireEvent.click(screen.getByText("Where is the key?"));
    expect(screen.queryByDisplayValue("Who forged the letter?")).toBeNull();
    expect(screen.getByDisplayValue("Where is the key?")).toBeInTheDocument();
  });

  it("collapses on clicking the open row's header again", async () => {
    render(ListValueEditor, { field: recordField, value: recordItems, onChange: () => {} });
    await fireEvent.click(screen.getByText("Who forged the letter?"));
    expect(screen.getByDisplayValue("Who forged the letter?")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("Who forged the letter?"));
    expect(screen.queryByDisplayValue("Who forged the letter?")).toBeNull();
  });

  it("editing a member emits the whole list with that member updated", async () => {
    const onChange = vi.fn();
    render(ListValueEditor, { field: recordField, value: recordItems, onChange });
    await fireEvent.click(screen.getByText("Who forged the letter?"));
    const input = screen.getByDisplayValue("Who forged the letter?");
    await fireEvent.input(input, { target: { value: "Who forged it, and when?" } });
    expect(onChange).toHaveBeenCalledWith([
      { question: "Who forged it, and when?", status: "open" },
      { question: "Where is the key?", status: "answered" },
    ]);
  });

  it("adds an empty record and removes by index", async () => {
    const onChange = vi.fn();
    render(ListValueEditor, { field: recordField, value: recordItems, onChange });
    await fireEvent.click(screen.getByText("+ Add item"));
    expect(onChange).toHaveBeenLastCalledWith([...(recordItems as unknown[]), {}]);
    const removeButtons = screen.getAllByRole("button", { name: "Remove item" });
    await fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenLastCalledWith([{ question: "Where is the key?", status: "answered" }]);
  });

  it("auto-opens the NEW row after add, not the one past it", async () => {
    // Regression (live-verified): the parent applies onChange synchronously,
    // so items has already grown when the open index is set — capturing
    // items.length after onChange opened index N+1 (nothing) instead of N.
    let value: MetadataValue = [...(recordItems as unknown[])] as MetadataValue;
    const onChange = vi.fn((next: MetadataValue) => {
      value = next;
    });
    const { rerender } = render(ListValueEditor, { field: recordField, value, onChange });
    await fireEvent.click(screen.getByText("+ Add item"));
    await rerender({ field: recordField, value, onChange });
    // The new (third, empty) row is the expanded one: its member editors are
    // present and empty, while the existing rows stay collapsed.
    const questionInput = screen.getByLabelText("Question") as HTMLInputElement;
    expect(questionInput.value).toBe("");
    expect(screen.queryByDisplayValue("Who forged the letter?")).toBeNull();
  });

  it("readOnly renders rows without grips, remove buttons, or the add row", () => {
    render(ListValueEditor, {
      field: recordField,
      value: recordItems,
      onChange: () => {},
      readOnly: true,
    });
    expect(screen.getByText("Who forged the letter?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove item" })).toBeNull();
    expect(screen.queryByText("+ Add item")).toBeNull();
  });
});

describe("ListValueEditor — scalar sugar (item_type)", () => {
  it("edits directly in the row (inline density, no expand step)", async () => {
    const onChange = vi.fn();
    render(ListValueEditor, { field: scalarField, value: ["Ash", "Harbor Rat"], onChange });
    const first = screen.getByDisplayValue("Ash");
    await fireEvent.input(first, { target: { value: "Ashlen" } });
    // Flat scalar storage: the emitted list stays a list of strings.
    expect(onChange).toHaveBeenCalledWith(["Ashlen", "Harbor Rat"]);
  });

  it("adds an empty scalar item", async () => {
    const onChange = vi.fn();
    render(ListValueEditor, { field: scalarField, value: ["Ash"], onChange });
    await fireEvent.click(screen.getByText("+ Add item"));
    expect(onChange).toHaveBeenLastCalledWith(["Ash", ""]);
  });

  it("treats a non-list value as empty rather than crashing", () => {
    render(ListValueEditor, { field: scalarField, value: "not-a-list", onChange: () => {} });
    expect(screen.getByText("+ Add item")).toBeInTheDocument();
  });
});

describe("ListValueEditor — shape-mismatched items (post shape-switch)", () => {
  it("renders a record item in a scalar list read-only instead of feeding a text input", () => {
    // A shape switch left a record behind in an item_type:text list. Feeding
    // it to the text editor would corrupt it on the first keystroke — it must
    // render as a read-only row (member values, not [object Object]).
    render(ListValueEditor, {
      field: scalarField,
      value: [{ question: "Who?", status: "open" }, "Ash"],
      onChange: () => {},
    });
    expect(screen.getByText("Who? · open")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("[object Object]")).toBeNull();
    // The matching item still edits normally.
    expect(screen.getByDisplayValue("Ash")).toBeInTheDocument();
  });

  it("renders a scalar item in a group list read-only with no expand", async () => {
    render(ListValueEditor, {
      field: recordField,
      value: ["stray string", { question: "Who?", status: "open" }],
      onChange: () => {},
    });
    const stray = screen.getByText("stray string");
    await fireEvent.click(stray);
    // No member editors opened for the mismatched row.
    expect(screen.queryByDisplayValue("stray string")).toBeNull();
  });
});

describe("ListValueEditor — entity_ref member picker (ADR-0081)", () => {
  const castField: MetadataFieldDefinition = {
    name: "Cast",
    type: "list",
    options: [],
    item_group: "cast",
    item_scalar: false,
    item_members: [
      {
        key: "who",
        name: "Who",
        type: "entity_ref",
        picker_config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
      },
    ],
  } as unknown as MetadataFieldDefinition;

  const loreRoster = [
    { id: "char_a", title: "Alice", body: "", entry_type: "lore:character", metadata: { tags: [], aliases: [] } },
  ] as unknown as import("@/lib/types").LoreEntrySummary[];

  it("threads the candidate roster so a member's ref picker resolves it (was empty)", async () => {
    // Regression for the two dropped boundaries: FieldValueEditor's list branch
    // and ListValueEditor's per-member editor must forward loreEntries, or the
    // nested picker filters an empty roster and shows no candidates.
    render(ListValueEditor, {
      field: castField,
      value: [{ who: "" }],
      onChange: () => {},
      loreEntries: loreRoster,
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add Who" }));
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });
});
