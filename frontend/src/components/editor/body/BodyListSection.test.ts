// @vitest-environment happy-dom
// BodyListSection (#2043): the repeating body section for a `list` field
// whose item shape carries a long_text member — a heading, then one
// sub-section per item (title, fact members as rail rows via BodyItemRows,
// long_text members as stacked editors). MetadataLongTextEditor is swapped
// for the same stub BodySections.test.ts uses (#642 — TipTap never mounts
// under happy-dom).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import BodyListSection from "./BodyListSection.svelte";
import type { BodyListSection as BodyListSectionType } from "@/lib/editor-core/bodySections";
import type { MetadataSchema, MetadataValue } from "@/lib/types";

vi.mock("@/components/widgets/MetadataLongTextEditor.svelte", async () => {
  const stub = await import("./BodySections.mockLongText.svelte");
  return { default: stub.default };
});

const SCHEMA = {
  version: 1,
  entry_types: {
    "plot:plotline": { name: "Plotline", kind: "plot", fields: ["beats"] },
  },
  fields: {
    beats: { name: "Beats", type: "list", options: [] },
  },
} as unknown as MetadataSchema;

const SECTION: BodyListSectionType = {
  id: "beats",
  label: "Beats",
  titleKey: "title",
  proseMembers: [
    { key: "function", name: "Function", type: "long_text" },
    { key: "guidance", name: "Guidance", type: "long_text" },
  ],
  factMembers: [
    { key: "required", name: "Required", type: "boolean" },
    { key: "id", name: "Id", type: "text" },
  ],
};

const ITEMS: MetadataValue[] = [
  { title: "Inciting toll", required: true, id: "toll-01", function: "Establish." },
  { title: "Refusal" },
];

function mount(items: MetadataValue[] = ITEMS, readOnly = false) {
  const onChange = vi.fn();
  const onEditorReady = vi.fn();
  const onNavigate = vi.fn();
  const { container } = render(BodyListSection, {
    props: {
      model: { section: SECTION, items, readOnly, schema: SCHEMA, entryType: "plot:plotline", documentKind: "plotline" },
      deps: {
        register: { register: () => {}, unregister: () => {}, neighboursFor: () => ({ prev: null, next: null }) },
        sectionIndex: () => 0,
        implicitContextMatcher: null,
        loreEntries: [],
        promptEntries: [],
        structure: null,
        researchStructure: null,
        excludeId: null,
        createLayerId: null,
        tagTitleById: new Map(),
      },
      on: { change: onChange, editorReady: onEditorReady, navigate: onNavigate },
    } as never,
  });
  return { container, onChange, onEditorReady, onNavigate };
}

describe("BodyListSection", () => {
  it("renders the list heading, item ordinals and titles", () => {
    const { container } = mount();
    const h2 = container.querySelector(".bs-h2")!;
    expect(h2.textContent).toContain("Beats");
    expect(h2.textContent).toContain("list · 2 items");
    const items = container.querySelectorAll(".bs-item");
    expect(items).toHaveLength(2);
    expect(items[0].querySelector(".bs-ord")?.textContent).toBe("1");
    expect(items[1].querySelector(".bs-ord")?.textContent).toBe("2");
    const titleInputs = container.querySelectorAll<HTMLInputElement>(".bs-item-title");
    expect(titleInputs[0].value).toBe("Inciting toll");
    expect(titleInputs[1].value).toBe("Refusal");
  });

  it("renders each item's prose members as stubbed long-text editors, headed Function/Guidance in order", () => {
    const { container } = mount();
    expect(container.querySelectorAll('[data-testid="mock-long-text"]')).toHaveLength(4);
    const h4s = Array.from(container.querySelectorAll(".bs-h4")).map((el) => el.textContent);
    expect(h4s).toEqual(["Function", "Guidance", "Function", "Guidance"]);
  });

  it("+ appends an item; × removes one", async () => {
    const { onChange } = mount();
    await fireEvent.click(screen.getByRole("button", { name: "Add Beats item" }));
    expect(onChange).toHaveBeenLastCalledWith([...ITEMS, {}]);

    const removeButtons = screen.getAllByRole("button", { name: /^Remove item/ });
    await fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenLastCalledWith([ITEMS[1]]);
  });

  it("editing item 2's title writes only that item's record", async () => {
    const { onChange } = mount();
    const input = screen.getByLabelText("Beats 2 title") as HTMLInputElement;
    await fireEvent.change(input, { target: { value: "Refusal, again" } });
    expect(onChange).toHaveBeenCalledWith([ITEMS[0], { title: "Refusal, again" }]);
  });

  it("Ctrl+ArrowDown on item 1 swaps the items; Ctrl+ArrowUp on item 1 is a no-op", async () => {
    const { onChange } = mount();
    const input1 = screen.getByLabelText("Beats 1 title") as HTMLInputElement;
    await fireEvent.keyDown(input1, { key: "ArrowDown", ctrlKey: true });
    expect(onChange).toHaveBeenCalledWith([ITEMS[1], ITEMS[0]]);
    onChange.mockClear();
    await fireEvent.keyDown(input1, { key: "ArrowUp", ctrlKey: true });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("item fact members render as rail rows, folding empties per item", async () => {
    const { container } = mount();
    const items = container.querySelectorAll(".bs-item");
    expect(items[0].querySelectorAll(".field-row")).toHaveLength(2);
    expect(items[0].querySelector('[data-testid="item-fold"]')).toBeNull();

    expect(items[1].querySelectorAll(".field-row")).toHaveLength(0);
    const fold = items[1].querySelector('[data-testid="item-fold"]') as HTMLElement;
    expect(fold).not.toBeNull();
    expect(fold.textContent).toBe("2 more fields ▸");

    await fireEvent.click(fold);
    expect(items[1].querySelectorAll(".field-row")).toHaveLength(2);
  });

  it("writing through a fact row updates that item's record only", async () => {
    const { container, onChange } = mount();
    const items = container.querySelectorAll(".bs-item");
    const idRow = Array.from(items[0].querySelectorAll(".field-row")).find((row) => row.textContent?.includes("Id"))!;
    const hit = idRow.querySelector(".fr-rest-hit") as HTMLElement;
    await fireEvent.click(hit);
    const input = idRow.querySelector("input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "toll-01x" } });
    expect(onChange).toHaveBeenCalledWith([{ ...(ITEMS[0] as Record<string, unknown>), id: "toll-01x" }, ITEMS[1]]);
  });

  it("readOnly: no inputs, no add/remove; prose renders as static text", () => {
    const { container } = mount(ITEMS, true);
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelector(".bs-add")).toBeNull();
    expect(container.querySelector(".bs-add-item")).toBeNull();
    expect(container.querySelector(".bs-remove")).toBeNull();
    expect(container.querySelectorAll(".fv-static-longtext")).toHaveLength(4);
  });
});
