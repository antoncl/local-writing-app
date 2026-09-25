// @vitest-environment happy-dom
// ReferenceListTab (#2010) — the body tab strip's full editor for one
// entity_ref_list field. ViewNodeList/NodeRow mount fine under happy-dom for
// a `hand_picked` + `group_by: entry_type` spec (see ViewNodeList.gate.test.ts
// and Lore.test.ts's #642 grouping pin) — this pins the tab's own wiring:
// grouping, remove, navigate, the Missing row, readOnly, and the filter box.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent, within } from "@/lib/test/component";
import ReferenceListTab from "./ReferenceListTab.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { bodyMemory } from "@/lib/stores/bodyMemory.svelte";
import { listTabSelectionKey, paneViews } from "@/lib/stores/paneViews.svelte";
import type { LoreEntrySummary, MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: [] },
    "lore:location": { name: "Location", kind: "lore", fields: [] },
  },
  fields: {
    kin: { name: "Kin", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
  },
} as unknown as MetadataSchema;

const KIN_FIELD = SCHEMA.fields.kin as MetadataFieldDefinition;

const LORE_ENTRIES: LoreEntrySummary[] = [
  { id: "char_tomas", title: "Tomas", body: "", entry_type: "lore:character", metadata: {} },
  { id: "char_elena", title: "Elena", body: "", entry_type: "lore:character", metadata: {} },
  { id: "loc_rivendell", title: "Rivendell", body: "", entry_type: "lore:location", metadata: {} },
];

function baseModel(over: Record<string, unknown> = {}) {
  return {
    field: KIN_FIELD,
    fieldId: "kin",
    entryType: "lore:character",
    fieldLabel: "Kin",
    items: ["char_tomas", "char_elena", "loc_rivendell"],
    keyMember: null,
    effectiveItems: null,
    readOnly: false,
    schema: SCHEMA,
    nodeId: "",
    ...over,
  };
}

function baseDeps(over: Record<string, unknown> = {}) {
  return {
    loreEntries: LORE_ENTRIES,
    promptEntries: [],
    assistantEntries: [],
    structure: null,
    researchStructure: null,
    ...over,
  };
}

function baseOn(over: Record<string, unknown> = {}) {
  return { change: vi.fn(), navigate: vi.fn(), ...over };
}

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

describe("ReferenceListTab (#2010)", () => {
  it("groups the three ids under Character / Location type heads, in that order", () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    expect(screen.getByText("Tomas")).toBeInTheDocument();
    expect(screen.getByText("Elena")).toBeInTheDocument();
    expect(screen.getByText("Rivendell")).toBeInTheDocument();
    const headings = Array.from(container.querySelectorAll(".node-row.group-header .node-row-text")).map((el) =>
      el.textContent?.trim(),
    );
    expect(headings).toEqual(["Character", "Location"]);
  });

  it("clicking × on Tomas calls on.change with the other two ids", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    await fireEvent.click(tomasRow.querySelector(".row-action-delete") as HTMLElement);
    expect(on.change).toHaveBeenCalledWith(["char_elena", "loc_rivendell"]);
  });

  it("double-clicking a row calls on.navigate with that id/kind/entryType", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on } });
    const elenaTitle = screen.getByText("Elena").closest("button.node-row-click") as HTMLElement;
    await fireEvent.dblClick(elenaTitle);
    expect(on.navigate).toHaveBeenCalledWith({ id: "char_elena", kind: "lore", entryType: "lore:character" });
  });

  it("an unknown id renders a Missing row with the .missing pill", () => {
    const { container } = render(ReferenceListTab, {
      props: {
        model: baseModel({ items: ["char_tomas", "ghost_1"] }),
        deps: baseDeps(),
        on: baseOn(),
      },
    });
    expect(screen.getAllByText("Missing").length).toBeGreaterThanOrEqual(2); // row title + type pill
    expect(container.querySelector(".ref-type-pill.missing")).not.toBeNull();
  });

  it("readOnly renders no × and no + (NodePicker trigger absent)", () => {
    const { container } = render(ReferenceListTab, {
      props: { model: baseModel({ readOnly: true }), deps: baseDeps(), on: baseOn() },
    });
    expect(container.querySelector(".row-action-delete")).toBeNull();
    expect(container.querySelector(".ref-list-add")).toBeNull();
  });

  it("the filter input narrows rows by title", async () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    const box = container.querySelector('input[type="search"]') as HTMLInputElement;
    await fireEvent.input(box, { target: { value: "riv" } });
    await tick();
    expect(screen.getByText("Rivendell")).toBeInTheDocument();
    expect(screen.queryByText("Tomas")).toBeNull();
    expect(screen.queryByText("Elena")).toBeNull();
  });
});

describe("ReferenceListTab — view switcher (#2039)", () => {
  const KEY = listTabSelectionKey("lore:character", "kin");
  const CHARACTERS_AZ = { kind: "lore", expr: { descendants_of: "lore:character" }, sort: { by: "title" } };

  beforeEach(() => {
    paneViews.reset();
    paneViews.views = { lore: [{ id: "view_az", title: "Characters A–Z", view_kind: "lore", spec: CHARACTERS_AZ } as never] };
    paneViews.specs = new Map([["view_az", CHARACTERS_AZ as never]]);
  });
  afterEach(() => {
    paneViews.reset();
    localStorage.clear();
  });

  it("renders the switcher in the tab head for a single-kind field", () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    expect(container.querySelector(".ref-list-head .view-switcher")).not.toBeNull();
  });

  it("a field whose sources span kinds gets no switcher (a view is anchored to one kind)", () => {
    const mixed = { ...KIN_FIELD, picker_config: { sources: [{ kind: "lore" }, { kind: "manuscript" }] } } as MetadataFieldDefinition;
    const { container } = render(ReferenceListTab, {
      props: { model: baseModel({ field: mixed }), deps: baseDeps(), on: baseOn() },
    });
    expect(container.querySelector(".view-switcher")).toBeNull();
  });

  it("the view chosen under the tab's own key shapes the tab's ids: filtered to characters, sorted by title, no type groups", () => {
    paneViews.select(KEY, "view_az");
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    const titles = Array.from(container.querySelectorAll(".node-row:not(.group-header) .node-row-text")).map((el) =>
      el.textContent?.trim(),
    );
    expect(titles).toEqual(["Elena", "Tomas"]);
    expect(container.querySelector(".node-row.group-header")).toBeNull();
    expect(screen.queryByText("Rivendell")).toBeNull();
  });

  it("the pane-kind selection does not leak into the tab", () => {
    paneViews.select("lore", "view_az");
    render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    expect(screen.getByText("Rivendell")).toBeInTheDocument();
  });
});

describe("ReferenceListTab — filter breadth (#2038)", () => {
  // The same predicate the Assistants pane uses: aliases and tag-node titles
  // (with the `#` restrictor) match, plus the entry-type name the pill shows.
  const ENTRIES: LoreEntrySummary[] = [
    { id: "char_tomas", title: "Tomas", body: "", entry_type: "lore:character", metadata: { tags: ["tag_night"] } },
    { id: "char_elena", title: "Elena", body: "", entry_type: "lore:character", metadata: { aliases: ["Ellie"] } },
    { id: "loc_rivendell", title: "Rivendell", body: "", entry_type: "lore:location", metadata: {} },
  ];
  const deps = () => baseDeps({ loreEntries: ENTRIES, tagTitleById: new Map([["tag_night", "night"]]) });

  async function filterTo(container: HTMLElement, value: string) {
    const box = container.querySelector('input[type="search"]') as HTMLInputElement;
    await fireEvent.input(box, { target: { value } });
    await tick();
  }

  it("an alias matches", async () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: deps(), on: baseOn() } });
    await filterTo(container, "ellie");
    expect(screen.getByText("Elena")).toBeInTheDocument();
    expect(screen.queryByText("Tomas")).toBeNull();
    expect(screen.queryByText("Rivendell")).toBeNull();
  });

  it("a tag-node title matches, through the # restrictor too", async () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: deps(), on: baseOn() } });
    await filterTo(container, "#night");
    expect(screen.getByText("Tomas")).toBeInTheDocument();
    expect(screen.queryByText("Elena")).toBeNull();
    expect(screen.queryByText("Rivendell")).toBeNull();
  });

  it("the entry-type name matches", async () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: deps(), on: baseOn() } });
    await filterTo(container, "location");
    expect(screen.getByText("Rivendell")).toBeInTheDocument();
    expect(screen.queryByText("Tomas")).toBeNull();
    expect(screen.queryByText("Elena")).toBeNull();
  });
});

describe("ReferenceListTab — peek card (#2011)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("hovering a row opens a peek card with its title", async () => {
    const { container } = render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on: baseOn() } });
    const anchor = screen.getByText("Tomas").closest(".ref-row-anchor") as HTMLElement;
    await fireEvent.mouseOver(anchor);
    vi.advanceTimersByTime(350);
    await tick();
    const card = container.ownerDocument.querySelector(".peek-card");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("Tomas");
  });

  it("clicking Remove on the card removes it from the list", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: baseModel(), deps: baseDeps(), on } });
    const anchor = screen.getByText("Tomas").closest(".ref-row-anchor") as HTMLElement;
    await fireEvent.mouseOver(anchor);
    vi.advanceTimersByTime(350);
    await tick();
    const card = document.querySelector(".peek-card") as HTMLElement;
    await fireEvent.click(within(card).getByText("× Remove"));
    expect(on.change).toHaveBeenCalledWith(["char_elena", "loc_rivendell"]);
  });
});

describe("ReferenceListTab — scroll memory (#2013)", () => {
  const NODE_ID = "char_tomas"; // any stable string; not resolved as a ref here

  afterEach(() => {
    bodyMemory.forget(NODE_ID);
    vi.unstubAllGlobals();
  });

  it("restores a remembered scroll position for this node/field on mount", async () => {
    bodyMemory.rememberScroll(NODE_ID, "list:kin", 120);
    const { container } = render(ReferenceListTab, {
      props: { model: baseModel({ nodeId: NODE_ID }), deps: baseDeps(), on: baseOn() },
    });
    await tick();
    await tick();
    const body = container.querySelector(".ref-list-body") as HTMLElement;
    expect(body.scrollTop).toBe(120);
  });

  it("scrolling the list records the position under list:<fieldId> for this node", async () => {
    let frame: FrameRequestCallback | null = null;
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: FrameRequestCallback) => {
        frame = cb;
        return 1;
      }),
    );
    const { container } = render(ReferenceListTab, {
      props: { model: baseModel({ nodeId: NODE_ID }), deps: baseDeps(), on: baseOn() },
    });
    await tick();
    const body = container.querySelector(".ref-list-body") as HTMLElement;
    Object.defineProperty(body, "scrollTop", { value: 40, writable: true });
    await fireEvent.scroll(body);
    (frame as unknown as FrameRequestCallback)(0);
    expect(bodyMemory.scrollFor(NODE_ID, "list:kin")).toBe(40);
  });
});

describe("ReferenceListTab — reference-keyed lists (ADR-0089 #2072)", () => {
  const REL_SCHEMA = {
    version: 1,
    entry_types: {
      "lore:character": { name: "Character", kind: "lore", fields: [] },
    },
    fields: {
      relationships: {
        name: "Relationships",
        type: "list",
        options: [],
        item_scalar: false,
        item_members: [
          { key: "to", name: "To", type: "entity_ref", picker_config: { sources: [{ kind: "lore" }] } },
          { key: "kind", name: "Kind", type: "text" },
          { key: "state", name: "State", type: "text" },
        ],
      },
    },
  } as unknown as MetadataSchema;
  const REL_FIELD = REL_SCHEMA.fields.relationships as MetadataFieldDefinition;
  const REL_ENTRIES: LoreEntrySummary[] = [
    { id: "char_tomas", title: "Tomas", body: "", entry_type: "lore:character", metadata: {} },
    { id: "char_elena", title: "Elena", body: "", entry_type: "lore:character", metadata: {} },
    { id: "char_mara", title: "Mara", body: "", entry_type: "lore:character", metadata: {} },
  ];

  function relModel(over: Record<string, unknown> = {}) {
    return {
      field: REL_FIELD,
      fieldId: "relationships",
      entryType: "lore:character",
      fieldLabel: "Relationships",
      items: [
        { to: "char_tomas", kind: "kinship", state: "estranged" },
        { to: "char_elena", kind: "rivalry", state: "" },
      ],
      keyMember: "to",
      effectiveItems: null,
      readOnly: false,
      schema: REL_SCHEMA,
      nodeId: "",
      ...over,
    };
  }
  const relDeps = (over: Record<string, unknown> = {}) => baseDeps({ loreEntries: REL_ENTRIES, ...over });

  beforeEach(() => metadataSchemaStore.set(REL_SCHEMA));

  it("rows render each non-key member as its own segment", () => {
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on: baseOn() } });
    expect(screen.getByText("Tomas")).toBeInTheDocument();
    expect(screen.getByText("kinship")).toBeInTheDocument();
    expect(screen.getByText("estranged")).toBeInTheDocument();
    expect(screen.getByText("Elena")).toBeInTheDocument();
    expect(screen.getByText("rivalry")).toBeInTheDocument();
    // Elena's blank `state` member shows the member's own name, muted —
    // ADR-0089 Amendment 2 (replaces #2218's "Add details…").
    const elenaRow = screen.getByText("Elena").closest(".node-row") as HTMLElement;
    const placeholder = within(elenaRow).getByText("State");
    expect(placeholder.className).toContain("idl-empty");
    // The key member ("to") never renders as a segment.
    expect(screen.queryByText("char_tomas")).toBeNull();
  });

  it("a key-only item's segments all show their member name as a placeholder", () => {
    const model = relModel({ items: [{ to: "char_mara" }] });
    const { container } = render(ReferenceListTab, { props: { model, deps: relDeps(), on: baseOn() } });
    const maraRow = screen.getByText("Mara").closest(".node-row") as HTMLElement;
    expect(within(maraRow).getByText("Kind")).toBeInTheDocument();
    expect(within(maraRow).getByText("State")).toBeInTheDocument();
    expect(container.querySelector(".ref-item-add-details")).toBeNull(); // #2218's opener is gone
  });

  it("clicking a text segment turns it into an input; Enter commits and leaves other items untouched", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    await fireEvent.click(within(tomasRow).getByText("kinship"));
    const input = within(tomasRow).getByDisplayValue("kinship") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "kin" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(on.change).toHaveBeenCalledWith([
      { to: "char_tomas", kind: "kin", state: "estranged" },
      { to: "char_elena", kind: "rivalry", state: "" },
    ]);
  });

  it("Esc on a segment's input reverts without saving", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    await fireEvent.click(within(tomasRow).getByText("kinship"));
    const input = within(tomasRow).getByDisplayValue("kinship") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "kin" } });
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(on.change).not.toHaveBeenCalled();
    expect(within(tomasRow).getByText("kinship")).toBeInTheDocument();
  });

  it("Tab commits the current segment and opens the next one for edit", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    await fireEvent.click(within(tomasRow).getByText("kinship"));
    const input = within(tomasRow).getByDisplayValue("kinship") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "kin" } });
    await fireEvent.keyDown(input, { key: "Tab" });
    expect(on.change).toHaveBeenCalledWith([
      { to: "char_tomas", kind: "kin", state: "estranged" },
      { to: "char_elena", kind: "rivalry", state: "" },
    ]);
    await tick();
    expect(within(tomasRow).getByDisplayValue("estranged")).toBeInTheDocument();
  });

  it("a select member's options open in ONE click, anchored on the segment; choosing one commits", async () => {
    const selectField = {
      ...REL_FIELD,
      item_members: [
        REL_FIELD.item_members![0],
        { key: "kind", name: "Kind", type: "select", options: [{ value: "ally", label: "Ally" }, { value: "rival", label: "Rival" }] },
        REL_FIELD.item_members![2],
      ],
    } as MetadataFieldDefinition;
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel({ field: selectField }), deps: relDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    // ONE click on the segment — no wrapper popover, no second click on a
    // nested trigger (the approved design's fix for the two-click deviation).
    await fireEvent.click(within(tomasRow).getByText("kinship"));
    // The list opens on the next task, after this click has bubbled (#2221).
    await new Promise((resolve) => setTimeout(resolve));
    await tick();
    expect(document.querySelector(".idl-popover")).toBeNull();
    const optionsPopover = document.querySelector(".colored-select-popover") as HTMLElement;
    expect(optionsPopover).not.toBeNull();
    await fireEvent.click(within(optionsPopover).getByText("Rival"));
    expect(on.change).toHaveBeenCalledWith([
      { to: "char_tomas", kind: "rival", state: "estranged" },
      { to: "char_elena", kind: "rivalry", state: "" },
    ]);
  });

  it("picking a new target appends an item with only the key set and keeps other items' members intact", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    await fireEvent.click(screen.getByRole("button", { name: "Add Relationships" }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByRole("button", { name: "Expand Character" }));
    await tick();
    await fireEvent.click(within(menu).getByText("Mara").closest("button")!);
    await tick();
    expect(on.change).toHaveBeenCalledWith([
      { to: "char_tomas", kind: "kinship", state: "estranged" },
      { to: "char_elena", kind: "rivalry", state: "" },
      { to: "char_mara" },
    ]);
  });

  it("adding a target puts the cursor in the new item's first segment", async () => {
    const on = baseOn();
    const { container, rerender } = render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    await fireEvent.click(screen.getByRole("button", { name: "Add Relationships" }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByRole("button", { name: "Expand Character" }));
    await tick();
    await fireEvent.click(within(menu).getByText("Mara").closest("button")!);
    await tick();
    // The host writes the change back; the tab re-renders with the new item.
    await rerender({
      model: relModel({
        items: [
          { to: "char_tomas", kind: "kinship", state: "estranged" },
          { to: "char_elena", kind: "rivalry", state: "" },
          { to: "char_mara" },
        ],
      }),
      deps: relDeps(),
      on,
    });
    await tick();
    const list = container.querySelector(".ref-list-body") as HTMLElement;
    const maraRow = within(list).getByText("Mara").closest(".node-row") as HTMLElement;
    expect(within(maraRow).getByRole("textbox")).toBeInTheDocument();
  });

  it("picking an already-picked target through the add menu removes it, never duplicates the key", async () => {
    // NodePicker's own toggle (`isPicked` against the `value` it's fed) turns
    // a re-pick of an already-selected candidate into a REMOVE, so a
    // duplicate-add can never reach the tab's fold through real interaction —
    // this is the shape that invariant takes end to end.
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    await fireEvent.click(screen.getByRole("button", { name: "Add Relationships" }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByRole("button", { name: "Expand Character" }));
    await tick();
    await fireEvent.click(within(menu).getByText("Tomas").closest("button")!);
    await tick();
    expect(on.change).toHaveBeenCalledWith([{ to: "char_elena", kind: "rivalry", state: "" }]);
  });

  it("remove (×) drops the right item, keeping the rest untouched", async () => {
    const on = baseOn();
    render(ReferenceListTab, { props: { model: relModel(), deps: relDeps(), on } });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    await fireEvent.click(tomasRow.querySelector(".row-action-delete") as HTMLElement);
    expect(on.change).toHaveBeenCalledWith([{ to: "char_elena", kind: "rivalry", state: "" }]);
  });

  it("an orphaned item (a blank key) renders as orphaned and can be removed", async () => {
    const on = baseOn();
    render(ReferenceListTab, {
      props: {
        model: relModel({
          items: [
            { to: "", kind: "kinship", state: "gone" },
            { to: "char_elena", kind: "rivalry", state: "" },
          ],
        }),
        deps: relDeps(),
        on,
      },
    });
    expect(screen.getByText("(no target)")).toBeInTheDocument();
    expect(screen.getByText("Orphaned")).toBeInTheDocument();
    const orphanRow = screen.getByText("(no target)").closest(".node-row") as HTMLElement;
    await fireEvent.click(orphanRow.querySelector(".row-action-delete") as HTMLElement);
    expect(on.change).toHaveBeenCalledWith([{ to: "char_elena", kind: "rivalry", state: "" }]);
  });

  it("a scrubbed effective item shows the mutation mark on its detail, read-only", () => {
    render(ReferenceListTab, {
      props: {
        model: relModel({
          readOnly: true,
          effectiveItems: [
            { to: "char_tomas", kind: "kinship", state: "reconciled" },
            { to: "char_elena", kind: "rivalry", state: "" },
          ],
        }),
        deps: relDeps(),
        on: baseOn(),
      },
    });
    const tomasRow = screen.getByText("Tomas").closest(".node-row") as HTMLElement;
    expect(within(tomasRow).getByTitle("Changed by here")).toBeInTheDocument();
    expect(within(tomasRow).getByText("kinship")).toBeInTheDocument();
    expect(within(tomasRow).getByText("reconciled")).toBeInTheDocument();
    // Read-only (scrubbed): the segments are plain text, not buttons.
    expect(tomasRow.querySelectorAll(".idl-seg-btn").length).toBe(0);
    const elenaRow = screen.getByText("Elena").closest(".node-row") as HTMLElement;
    expect(within(elenaRow).queryByTitle("Changed by here")).toBeNull();
  });
});
