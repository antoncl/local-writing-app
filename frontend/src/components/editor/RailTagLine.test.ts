// @vitest-environment happy-dom
// #2007 — a tags field renders and edits as ONE mono line, never pills. This
// covers RailTagLine directly: the rest line's grouping (single vs. multi
// vocabulary), the empty/missing states, and the editing input's completion +
// create-missing + backspace/escape keyboard contract.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent, within } from "@/lib/test/component";
import RailTagLine from "./RailTagLine.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes, tagNodesStore } from "@/lib/stores/tagNodes";
import { referenceIndexStore, clearReferenceIndex } from "@/lib/stores/references";
import { api } from "@/lib/api";
import type { LoreEntrySummary, MetadataFieldDefinition, MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "tag:theme": { name: "Theme", kind: "tag" },
    "tag:house": { name: "House", kind: "tag" },
  },
  fields: {},
} as unknown as MetadataSchema;

const TAGS: TagEntry[] = [
  { id: "tag_pov", title: "pov", entry_type: "tag:house", metadata: {} },
  { id: "tag_river", title: "river", entry_type: "tag:house", metadata: {} },
  { id: "tag_guilt", title: "guilt", entry_type: "tag:theme", metadata: {} },
  { id: "tag_fire", title: "fire", entry_type: "tag:theme", metadata: {} },
  { id: "tag_guardian", title: "guardian", entry_type: "tag:theme", metadata: {} },
];

// A field with no fixed vocabulary — display grouping is driven purely by the
// VALUE's resolved tags, not the field's own picker scope.
const openField = {
  name: "Tags",
  type: "entity_ref_list",
  options: [],
  picker_config: { sources: [{ kind: "tag" }] },
} as unknown as MetadataFieldDefinition;

// A field scoped to one vocabulary, with create_missing on — needed for the
// create-path tests (`createTargetFor` requires a single concrete target).
const themeField = {
  name: "Tags",
  type: "entity_ref_list",
  options: [],
  picker_config: { sources: [{ kind: "tag", expr: { type: "tag:theme" } }], create_missing: true },
} as unknown as MetadataFieldDefinition;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  tagNodesStore.set(TAGS);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearTagNodes();
  metadataSchemaStore.set(null);
});

const noop = () => {};

describe("RailTagLine — rest display grouping", () => {
  it("one vocabulary: joins titles with no prefix", () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_pov", "tag_river"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const hit = screen.getByTestId("rail-tag-line");
    expect(hit.textContent).toBe("pov · river");
    expect(hit.querySelector(".tag-line-vocab")).toBeNull();
  });

  it("two vocabularies: vocab-labelled groups joined by the divider", () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_guilt", "tag_pov"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    expect(screen.getByText("Theme:")).toBeInTheDocument();
    expect(screen.getByText("House:")).toBeInTheDocument();
    const hit = screen.getByTestId("rail-tag-line");
    expect(hit.querySelector(".tag-line-divider")).toBeInTheDocument();
  });

  it("empty: the bare + glyph and an aria-label naming the field", () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const hit = screen.getByTestId("rail-tag-line");
    expect(hit.textContent).toBe("+");
    expect(hit).toHaveAttribute("aria-label", "Set Tags");
  });

  it("a missing id renders its raw id with the missing treatment", () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_nope"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const missing = screen.getByText("tag_nope");
    expect(missing).toHaveClass("missing");
  });
});

describe("RailTagLine — editing", () => {
  it("focuses the input on entering edit mode", async () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: true,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await vi.waitFor(() => expect(input).toHaveFocus());
  });

  it("typing filters candidates to matches, excluding an already-selected tag; ArrowDown+Enter picks", async () => {
    const onChange = vi.fn();
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_guilt"],
        editing: true,
        onOpen: noop,
        onClose: noop,
        onChange,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "gu" } });
    // "guilt" is already selected (and shown as a committed token) — the
    // CANDIDATE list must exclude it, offering only "guardian".
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).queryByText("guilt")).not.toBeInTheDocument();
    expect(within(listbox).getByText("guardian")).toBeInTheDocument();
    await fireEvent.keyDown(input, { key: "ArrowDown" });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["tag_guilt", "tag_guardian"]);
    expect(input).toHaveValue("");
  });

  it("Enter on an unknown title with createLayerId set mints a tag via resolveOrCreateTag", async () => {
    const createSpy = vi
      .spyOn(api, "createTagEntry")
      .mockResolvedValue({ id: "tag_new", title: "Mystery", entry_type: "tag:theme", metadata: {} } as TagEntry);
    const onChange = vi.fn();
    render(RailTagLine, {
      props: {
        field: themeField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: true,
        createLayerId: "layer_x",
        onOpen: noop,
        onClose: noop,
        onChange,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "Mystery" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith(["tag_new"]));
    expect(createSpy).toHaveBeenCalledWith("Mystery", "tag:theme", null, "layer_x");
    expect(input).toHaveValue("");
  });

  it("a second Enter while a create is in flight does not mint twice", async () => {
    let resolveCreate: (tag: TagEntry) => void = () => {};
    const createSpy = vi.spyOn(api, "createTagEntry").mockImplementation(
      () => new Promise<TagEntry>((resolve) => { resolveCreate = resolve; }),
    );
    const onChange = vi.fn();
    render(RailTagLine, {
      props: { field: themeField, fieldId: "tags", fieldLabel: "Tags", value: [], editing: true, createLayerId: null, onOpen: noop, onClose: noop, onChange },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "Mystery" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(createSpy).toHaveBeenCalledTimes(1);
    resolveCreate({ id: "tag_new", title: "Mystery", entry_type: "tag:theme", metadata: {} } as TagEntry);
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith(["tag_new"]));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("a failed create shows the error line and keeps the typed title", async () => {
    vi.spyOn(api, "createTagEntry").mockRejectedValue(new Error("layer is read-only"));
    render(RailTagLine, {
      props: { field: themeField, fieldId: "tags", fieldLabel: "Tags", value: [], editing: true, createLayerId: null, onOpen: noop, onClose: noop, onChange: noop },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "Mystery" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await vi.waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("layer is read-only"));
    expect(input).toHaveValue("Mystery");
  });

  it("retyping a title already on the node offers no Create option", async () => {
    render(RailTagLine, {
      props: { field: themeField, fieldId: "tags", fieldLabel: "Tags", value: ["tag_guilt"], editing: true, createLayerId: null, onOpen: noop, onClose: noop, onChange: noop },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "guilt" } });
    expect(screen.queryByTestId("tag-line-create")).toBeNull();
  });

  it("the input is a combobox naming the highlighted option", async () => {
    render(RailTagLine, {
      props: { field: openField, fieldId: "tags", fieldLabel: "Tags", value: [], editing: true, onOpen: noop, onClose: noop, onChange: noop },
    });
    const input = screen.getByLabelText("Add Tags");
    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-expanded", "false");
    await fireEvent.input(input, { target: { value: "gu" } });
    expect(input).toHaveAttribute("aria-expanded", "true");
    const listbox = screen.getByRole("listbox");
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    const first = within(listbox).getAllByRole("option")[0];
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    await fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", within(listbox).getAllByRole("option")[1].id);
  });

  it("createLayerId null means 'this project' — the create option IS offered (the rail's scene case)", async () => {
    render(RailTagLine, {
      props: {
        field: themeField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: true,
        createLayerId: null,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "Mystery" } });
    expect(screen.getByTestId("tag-line-create")).toBeInTheDocument();
  });

  it("without createLayerId (undefined), no create option renders for an unknown title", async () => {
    render(RailTagLine, {
      props: {
        field: themeField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: true,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.input(input, { target: { value: "Mystery" } });
    expect(screen.queryByTestId("tag-line-create")).toBeNull();
  });

  it("Backspace on an empty input removes the last committed tag", async () => {
    const onChange = vi.fn();
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_pov", "tag_river"],
        editing: true,
        onOpen: noop,
        onClose: noop,
        onChange,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.keyDown(input, { key: "Backspace" });
    expect(onChange).toHaveBeenCalledWith(["tag_pov"]);
  });

  it("Escape closes the row", async () => {
    const onClose = vi.fn();
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: [],
        editing: true,
        onOpen: noop,
        onClose,
        onChange: noop,
      },
    });
    const input = screen.getByLabelText("Add Tags");
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledWith("tags");
  });
});

describe("RailTagLine — peek card at rest (#2011)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    clearReferenceIndex();
  });

  it("hovering a name on the rest line opens the tag's peek card", async () => {
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_pov", "tag_river"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
      },
    });
    const name = screen.getByText("pov");
    await fireEvent.mouseOver(name);
    vi.advanceTimersByTime(350);
    await tick();
    const card = document.querySelector(".peek-card");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("pov");
  });

  it("Remove on the card drops that id from the value", async () => {
    const onChange = vi.fn();
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_pov", "tag_river"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange,
      },
    });
    const name = screen.getByText("pov");
    await fireEvent.mouseOver(name);
    vi.advanceTimersByTime(350);
    await tick();
    const card = document.querySelector(".peek-card") as HTMLElement;
    await fireEvent.click(within(card).getByText("× Remove"));
    expect(onChange).toHaveBeenCalledWith(["tag_river"]);
  });

  it("the breakdown reads a real kind (Lore), not Other, when the carrier resolves via threaded deps", async () => {
    // Same reference-index fixture shape peekTarget.test.ts uses: the tag's
    // carriers are its reverse-index entry — a lore entry here.
    referenceIndexStore.set(new Map([["tag_pov", new Set(["lore_1"])]]));
    const loreEntries: LoreEntrySummary[] = [
      { id: "lore_1", title: "Mira", body: "", entry_type: "lore:character", metadata: {} },
    ];
    render(RailTagLine, {
      props: {
        field: openField,
        fieldId: "tags",
        fieldLabel: "Tags",
        value: ["tag_pov"],
        editing: false,
        onOpen: noop,
        onClose: noop,
        onChange: noop,
        deps: { loreEntries },
      },
    });
    const name = screen.getByText("pov");
    await fireEvent.mouseOver(name);
    vi.advanceTimersByTime(350);
    await tick();
    const card = document.querySelector(".peek-card") as HTMLElement;
    expect(card.textContent).toContain("carried by 1 node");
    expect(within(card).getByText("Lore")).toBeInTheDocument();
    expect(within(card).queryByText("Other")).not.toBeInTheDocument();
  });
});
