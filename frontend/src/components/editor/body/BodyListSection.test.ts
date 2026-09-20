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

const registerFocus = vi.fn();

function mount(items: MetadataValue[] = ITEMS, readOnly = false, density?: "prose" | "compact", section: BodyListSectionType = SECTION) {
  const onChange = vi.fn();
  const onEditorReady = vi.fn();
  const onNavigate = vi.fn();
  const { container } = render(BodyListSection, {
    props: {
      model: { section, items, readOnly, schema: SCHEMA, entryType: "plot:plotline", documentKind: "plotline", density },
      deps: {
        register: { register: () => {}, unregister: () => {}, neighboursFor: () => ({ prev: null, next: null }), focus: registerFocus },
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

  it("Ctrl+ArrowDown from inside a prose member reorders the item and refocuses that member at its new index (#2052)", async () => {
    registerFocus.mockClear();
    const { container, onChange } = mount();
    // Item 1's second prose member (Guidance) — the chord comes from its editor, not the title.
    const guidance = container.querySelectorAll(".bs-item")[0].querySelectorAll('[data-testid="mock-long-text"]')[1];
    await fireEvent.keyDown(guidance, { key: "ArrowDown", ctrlKey: true });
    expect(onChange).toHaveBeenCalledWith([ITEMS[1], ITEMS[0]]);
    expect(registerFocus).toHaveBeenCalledWith("beats[1].guidance");
  });

  it("an item shape with no title member still reorders by keyboard from its prose (#2052)", async () => {
    const noTitle: BodyListSectionType = { ...SECTION, titleKey: null, factMembers: [] };
    const { container, onChange } = mount([{ function: "one" }, { function: "two" }], false, undefined, noTitle);
    expect(container.querySelector(".bs-item-title")).toBeNull();
    const second = container.querySelectorAll(".bs-item")[1].querySelector('[data-testid="mock-long-text"]')!;
    await fireEvent.keyDown(second, { key: "ArrowUp", ctrlKey: true });
    expect(onChange).toHaveBeenCalledWith([{ function: "two" }, { function: "one" }]);
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

  it("compact density sets the class and renders no id on the root (#2043 slice 3)", () => {
    const { container } = mount(ITEMS, false, "compact");
    const root = container.querySelector(".bs-block")!;
    expect(root.classList.contains("compact")).toBe(true);
    expect(root.id).toBe("");
  });

  it("default (prose) density keeps the section-{id} anchor", () => {
    const { container } = mount();
    const root = container.querySelector(".bs-block")!;
    expect(root.classList.contains("compact")).toBe(false);
    expect(root.id).toBe("section-beats");
  });

  it("flags an empty long_text member so it rests as one line; a filled one is a block (#2047)", () => {
    // Item 1 has Function text and no Guidance; item 2 has neither.
    const { container } = mount();
    const members = [...container.querySelectorAll(".bs-member")];
    expect(members).toHaveLength(4);
    expect(members.map((m) => m.classList.contains("is-empty"))).toEqual([false, true, true, true]);
    // The label stays inside the member block, so the one-line rest state keeps its name.
    expect(members[1].querySelector(".bs-h4")?.textContent).toBe("Guidance");
  });
});
