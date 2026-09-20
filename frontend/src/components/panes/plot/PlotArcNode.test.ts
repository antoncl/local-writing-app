// @vitest-environment happy-dom
// PlotArcNode RENDER guard (ADR-0080 §5 / Amendment 1) — mirrors PlotPlotlineNode.test.ts.
// A character arc is a first-class board node that must DISPLAY its title, its seedling
// glyph (the arc-vs-plotline discriminator), and its bound character, and — like every
// list-rendering pane — a mount test asserts the content renders
// ([[reference_component_test_harness]]). The node imports nothing from @xyflow/svelte,
// so it mounts here on its own (the SvelteFlow canvas is not headless).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { waitFor } from "@testing-library/svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import PlotArcNode from "./PlotArcNode.svelte";
import type { PlotArcData } from "@/lib/plot/plotBoardLayout";
import { PLOT_ARC_ACTIONS, type PlotArcActions } from "./plotArcActions";
import { PLOT_DND_MIME } from "@/lib/plot/plotDnd";
import type { CharacterArcEntry, MetadataSchema } from "@/lib/types";

// PlotBeatSections/BodyListSection (#2043 slice 3) now render the beats; TipTap never
// mounts under happy-dom (#642), so MetadataLongTextEditor is swapped for the stub.
vi.mock("@/components/widgets/MetadataLongTextEditor.svelte", async () => {
  const stub = await import("@/components/editor/body/BodySections.mockLongText.svelte");
  return { default: stub.default };
});

const SCHEMA = {
  version: 1,
  entry_types: {
    "plot:plotline": { name: "Plotline", kind: "plot", fields: ["instance_beats"] },
    "plot:character_arc": { name: "Character arc", kind: "plot", fields: ["instance_beats"] },
  },
  fields: {
    instance_beats: {
      name: "Specialized beats",
      type: "list",
      options: [],
      item_members: [
        { key: "title", name: "Title", type: "text" },
        { key: "function", name: "Function", type: "long_text" },
        { key: "guidance", name: "Guidance", type: "long_text" },
        { key: "specifics", name: "Specifics", type: "long_text" },
        { key: "required", name: "Required", type: "boolean" },
        { key: "id", name: "Id", type: "text" },
      ],
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

const data = (over: Partial<PlotArcData> = {}): PlotArcData => ({
  title: "Elena's redemption",
  color: null,
  beats: [
    { beat_id: "b1", title: "Denial", use_count: 2 },
    { beat_id: "b2", title: "Acceptance", use_count: 0 },
  ],
  characterId: "char_1",
  characterName: "Elena",
  characterInitial: "E",
  resolvedColorHex: null,
  ...over,
});

// The full arc entry the on-node editor loads on expand (the board projection only
// carries beat titles + the resolved character display fields, not the editable id).
const entry = (): CharacterArcEntry => ({
  id: "arc_1",
  title: "Elena's redemption",
  body: "",
  revision: "r1",
  entry_type: "plot:character_arc",
  metadata: {
    color: null,
    character: "char_1",
    instance_beats: [
      { title: "Denial", function: "", guidance: "", specifics: "", required: true, id: "b1" },
      { title: "Acceptance", function: "", guidance: "", specifics: "", required: true, id: "b2" },
    ],
  },
  computed_metadata: {},
});

function fakeActions(over: Partial<PlotArcActions> = {}) {
  const saved: CharacterArcEntry[] = [];
  const deleted: string[] = [];
  const boundCharacters: Array<{ id: string; characterId: string }> = [];
  const actions: PlotArcActions = {
    expandedId: "arc_1",
    toggleExpanded: () => {},
    loadArc: async () => entry(),
    save: async (e) => {
      saved.push(e);
      return { ...e, revision: "r2" };
    },
    setCharacter: async (id, characterId) => {
      boundCharacters.push({ id, characterId });
      return { ...entry(), metadata: { ...entry().metadata, character: characterId }, revision: "r2" };
    },
    onDelete: (id) => deleted.push(id),
    ...over,
  };
  return {
    actions,
    saved,
    deleted,
    boundCharacters,
    mount: (props: Record<string, unknown> = {}) => {
      const result = render(PlotArcNode, {
        props: { id: "arc_1", data: data(), ...props },
        context: new Map<symbol, unknown>([[PLOT_ARC_ACTIONS, actions]]),
      });
      return { ...result, saved, deleted, boundCharacters };
    },
  };
}

describe("PlotArcNode", () => {
  it("renders the arc title and its whole change-beat roster in order", () => {
    render(PlotArcNode, { props: { data: data() } });
    expect(screen.getByText("Elena's redemption")).toBeTruthy();
    const beats = screen.getAllByRole("listitem").map((li) => li.querySelector(".beat-title")?.textContent);
    expect(beats).toEqual(["Denial", "Acceptance"]);
  });

  it("renders the seedling glyph — the arc-vs-plotline discriminator (Amendment 1 §2)", () => {
    const { container } = render(PlotArcNode, { props: { data: data() } });
    expect(container.querySelector(".arc-glyph i.ti-seedling")).not.toBeNull();
  });

  it("shows the bound character's name and a single-letter avatar, at rest", () => {
    render(PlotArcNode, { props: { data: data() } });
    expect(screen.getByText("Elena")).toBeTruthy();
    expect(screen.getByText("E")).toBeTruthy();
  });

  it("reads as unbound when no character is bound", () => {
    render(PlotArcNode, { props: { data: data({ characterId: null, characterName: null, characterInitial: null }) } });
    expect(screen.getByText("No character bound")).toBeTruthy();
  });

  it("shows an empty hint and no list when the arc has no beats yet", () => {
    render(PlotArcNode, { props: { data: data({ beats: [] }) } });
    expect(screen.getByText("No change beats yet")).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("stays read-only with no actions context (the mount-test degrade) — does not throw", () => {
    expect(() => render(PlotArcNode, { props: { data: data() } })).not.toThrow();
    expect(screen.queryByPlaceholderText("Arc name")).toBeNull();
    expect(screen.queryByRole("button", { name: /Add item/ })).toBeNull();
  });
});

describe("PlotArcNode beat drag source (ADR-0080 §5, mirrors ADR-0053 §4)", () => {
  it("makes each read-only beat draggable and writes the (arc, beat, holder_kind) payload on dragstart", async () => {
    render(PlotArcNode, { props: { id: "arc_1", data: data() } });
    const beats = screen.getAllByRole("listitem");
    expect(beats.every((li) => li.getAttribute("draggable") === "true")).toBe(true);

    const setData = vi.fn();
    const dataTransfer = { setData, effectAllowed: "none" } as unknown as DataTransfer;
    await fireEvent.dragStart(beats[0], { dataTransfer });
    // holder_kind rides the wire because it's non-default (a change-beat, not a
    // plotline event-beat) — the arc-as-primary guard (§4) reads it downstream.
    expect(setData).toHaveBeenCalledWith(
      PLOT_DND_MIME,
      JSON.stringify({ kind: "beat", plotline: "arc_1", beat_id: "b1", holder_kind: "plot:character_arc" }),
    );
  });

  it("does not make beats draggable without a node id (the mount-test degrade)", () => {
    render(PlotArcNode, { props: { data: data() } }); // no id
    const beats = screen.getAllByRole("listitem");
    expect(beats.every((li) => li.getAttribute("draggable") !== "true")).toBe(true);
  });
});

describe("PlotArcNode on-node editing (ADR-0080 §5)", () => {
  it("does not expand when its id isn't the board's expanded one", () => {
    fakeActions({ expandedId: null }).mount();
    expect(screen.queryByPlaceholderText("Arc name")).toBeNull();
    expect(screen.getByText("Denial")).toBeTruthy();
  });

  it("expands into an editor that loads the arc's name and beats", async () => {
    fakeActions().mount();
    const name = await screen.findByPlaceholderText("Arc name");
    expect((name as HTMLInputElement).value).toBe("Elena's redemption");
    const beatInputs = screen.getAllByRole("textbox", { name: /Specialized beats \d+ title/ }) as HTMLInputElement[];
    expect(beatInputs.map((i) => i.value)).toEqual(["Denial", "Acceptance"]);
  });

  it("renaming the arc saves the edited entry", async () => {
    const { saved } = fakeActions().mount();
    const name = (await screen.findByPlaceholderText("Arc name")) as HTMLInputElement;
    await fireEvent.input(name, { target: { value: "Elena's fall" } });
    await fireEvent.blur(name);
    await waitFor(() => expect(saved.length).toBe(1));
    expect(saved[0].title).toBe("Elena's fall");
  });

  it("adding a beat saves a roster with the new beat appended", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Arc name");
    await fireEvent.click(screen.getByRole("button", { name: "+ Add item" }));
    // The section save is debounced (SECTION_SAVE_DEBOUNCE_MS).
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 2000 });
    const beats = saved[0].metadata.instance_beats as Array<Record<string, unknown>>;
    expect(beats).toHaveLength(3);
    expect(beats[0].title).toBe("Denial");
    expect(beats[1].title).toBe("Acceptance");
    expect(beats[2]).toEqual({});
  });

  it("a beat title edit saves the roster with the new title and the beat's other members intact", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Arc name");
    const input = screen.getByRole("textbox", { name: "Specialized beats 1 title" }) as HTMLInputElement;
    await fireEvent.change(input, { target: { value: "Renamed denial" } });
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 2000 });
    const beats = saved[0].metadata.instance_beats as Array<Record<string, unknown>>;
    expect(beats[0]).toEqual({
      title: "Renamed denial",
      function: "",
      guidance: "",
      specifics: "",
      required: true,
      id: "b1",
    });
  });

  it("the expanded editor offers Delete character arc, which calls onDelete", async () => {
    const { deleted } = fakeActions().mount();
    const del = await screen.findByRole("button", { name: "Delete character arc" });
    await fireEvent.click(del);
    expect(deleted).toEqual(["arc_1"]);
  });
});

describe("PlotArcNode actions kebab", () => {
  it("surfaces Delete without expanding — the kebab's Delete calls onDelete", async () => {
    const { deleted } = fakeActions({ expandedId: null }).mount();
    expect(screen.queryByRole("button", { name: "Delete character arc" })).toBeNull(); // collapsed: no foot-actions
    await fireEvent.click(screen.getByRole("button", { name: "Character arc actions" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Delete character arc" }));
    expect(deleted).toEqual(["arc_1"]);
  });

  it("offers no kebab without an actions context (the read-only mount degrade)", () => {
    render(PlotArcNode, { props: { id: "arc_1", data: data() } });
    expect(screen.queryByRole("button", { name: "Character arc actions" })).toBeNull();
  });
});
