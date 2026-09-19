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
    ids: ["char_tomas", "char_elena", "loc_rivendell"],
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
        model: baseModel({ ids: ["char_tomas", "ghost_1"] }),
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
