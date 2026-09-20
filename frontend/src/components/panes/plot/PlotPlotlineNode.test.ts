// @vitest-environment happy-dom
// PlotPlotlineNode RENDER guard (ADR-0053 §3). A plotline is a first-class board node
// that must DISPLAY its beat roster, so — like PlotCardNode — a mount test asserts the
// content renders ([[reference_component_test_harness]]). The node imports nothing from
// @xyflow/svelte, so it mounts here on its own (the SvelteFlow canvas is not headless).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { waitFor } from "@testing-library/svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import PlotPlotlineNode from "./PlotPlotlineNode.svelte";
import type { PlotPlotlineData } from "@/lib/plot/plotBoardLayout";
import { PLOT_PLOTLINE_ACTIONS, type PlotPlotlineActions } from "./plotPlotlineActions";
import { PLOT_DND_MIME } from "@/lib/plot/plotDnd";
import type { MetadataSchema, MetadataValue, PlotlineEntry } from "@/lib/types";

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

const data = (over: Partial<PlotPlotlineData> = {}): PlotPlotlineData => ({
  title: "Main plot",
  color: null,
  beats: [
    { beat_id: "b1", title: "Setup", use_count: 2 },
    { beat_id: "b2", title: "Confrontation", use_count: 0 },
    { beat_id: "b3", title: "Resolution", use_count: 1 },
  ],
  ...over,
});

// A full plotline entry the on-node editor loads on expand (the board projection only
// carries beat titles, so editing loads the whole thing).
const entry = (): PlotlineEntry => ({
  id: "line_1",
  title: "Main plot",
  body: "",
  revision: "r1",
  entry_type: "plot:plotline",
  metadata: {
    color: null,
    instance_beats: [
      { title: "Setup", function: "", guidance: "", specifics: "", required: true, id: "b1" },
      { title: "Confrontation", function: "", guidance: "", specifics: "", required: true, id: "b2" },
    ],
  },
  computed_metadata: {},
});

// A fake actions context. `expandedId` decides whether the node opens its editor;
// loadPlotline feeds the draft; save records what was flushed and advances the revision.
function fakeActions(over: Partial<PlotPlotlineActions> = {}) {
  const saved: PlotlineEntry[] = [];
  const deleted: string[] = [];
  const actions: PlotPlotlineActions = {
    expandedId: "line_1",
    toggleExpanded: () => {},
    focusedId: null,
    toggleFocus: () => {},
    loadPlotline: async () => entry(),
    save: async (e) => {
      saved.push(e);
      return { ...e, revision: "r2" };
    },
    onDelete: (id) => deleted.push(id),
    ...over,
  };
  return {
    actions,
    saved,
    deleted,
    mount: (props: Record<string, unknown> = {}) => {
      const result = render(PlotPlotlineNode, {
        props: { id: "line_1", data: data(), ...props },
        context: new Map<symbol, unknown>([[PLOT_PLOTLINE_ACTIONS, actions]]),
      });
      return { ...result, saved, deleted };
    },
  };
}

beforeEach(() => metadataSchemaStore.set(SCHEMA));

describe("PlotPlotlineNode", () => {
  it("renders the plotline title and its whole beat roster in order", () => {
    render(PlotPlotlineNode, { props: { data: data() } });
    expect(screen.getByText("Main plot")).toBeTruthy();
    const beats = screen.getAllByRole("listitem").map((li) => li.querySelector(".beat-title")?.textContent);
    expect(beats).toEqual(["Setup", "Confrontation", "Resolution"]);
  });

  it("shows the beat count", () => {
    render(PlotPlotlineNode, { props: { data: data() } });
    expect(screen.getByTitle("Beats").textContent).toBe("3");
  });

  it("shows each beat's use-count, flagging a 0 as a gap (ADR-0053 §6 / S5a)", () => {
    render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    const counts = screen.getAllByRole("listitem").map((li) => li.querySelector(".beat-use"));
    expect(counts.map((c) => c?.textContent)).toEqual(["2", "0", "1"]);
    // Only the unfulfilled beat is flagged as a gap.
    expect(counts.map((c) => c?.classList.contains("gap"))).toEqual([false, true, false]);
  });

  it("shows an empty hint and no list when the plotline has no beats (ad-hoc)", () => {
    render(PlotPlotlineNode, { props: { data: data({ beats: [] }) } });
    expect(screen.getByText("No beats yet")).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByTitle("Beats").textContent).toBe("0");
  });

  it("renders without a colour (a colourless plotline is neutral, not broken)", () => {
    render(PlotPlotlineNode, { props: { data: data({ color: null }) } });
    expect(screen.getByText("Main plot")).toBeTruthy();
  });

  it("stays read-only with no actions context (the S2a / mount-test degrade)", () => {
    render(PlotPlotlineNode, { props: { data: data() } });
    // No editor: the roster shows as text, not inputs, and there's no Add-item control.
    expect(screen.queryByPlaceholderText("Plotline name")).toBeNull();
    expect(screen.queryByRole("button", { name: /Add item/ })).toBeNull();
  });
});

describe("PlotPlotlineNode beat drag source (ADR-0053 §4)", () => {
  it("makes each read-only beat draggable and writes the (plotline, beat) payload on dragstart", async () => {
    render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    const beats = screen.getAllByRole("listitem");
    expect(beats.every((li) => li.getAttribute("draggable") === "true")).toBe(true);
    // dragstart writes the beat-drag payload under the shared plot-DnD MIME so a card
    // can accept it (the drop side is unchanged). Each carries the SvelteFlow node's
    // reposition off via `nodrag` so grabbing a beat doesn't move the plotline.
    expect(beats.every((li) => li.classList.contains("nodrag"))).toBe(true);

    const setData = vi.fn();
    const dataTransfer = { setData, effectAllowed: "none" } as unknown as DataTransfer;
    await fireEvent.dragStart(beats[0], { dataTransfer });
    expect(setData).toHaveBeenCalledWith(
      PLOT_DND_MIME,
      JSON.stringify({ kind: "beat", plotline: "line_1", beat_id: "b1" }),
    );
  });

  it("shows a drag-handle grip on each draggable beat (#911)", () => {
    const { container } = render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    const grips = container.querySelectorAll(".plotline-beat .beat-grip");
    expect(grips.length).toBe(screen.getAllByRole("listitem").length);
  });

  it("does not make beats draggable (or grip them) without a node id (the mount-test degrade)", () => {
    const { container } = render(PlotPlotlineNode, { props: { data: data() } }); // no id
    const beats = screen.getAllByRole("listitem");
    expect(beats.every((li) => li.getAttribute("draggable") !== "true")).toBe(true);
    expect(container.querySelectorAll(".beat-grip").length).toBe(0); // no grip when not draggable
  });

  // The node drag handle (#876) — distinct from the per-beat grips above: the whole
  // plotline drags by this one leading handle, the same affordance a card uses, so its
  // header's focus/expand controls stay click-only. Present on an interactive board only.
  it("renders the node drag-handle grip in its header, and omits it read-only (#876)", () => {
    const { container } = fakeActions({ expandedId: null }).mount();
    const grip = container.querySelector(".plotline-head .plotline-drag-handle");
    expect(grip).not.toBeNull();
    // The app's standard grip icon (a generous, hittable handle — not a collapsing glyph).
    expect(grip!.querySelector("i.ti-grip-vertical")).not.toBeNull();
    // No actions (read-only mount / non-interactive board) → nothing to drag, no handle.
    const { container: ro } = render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    expect(ro.querySelector(".plotline-drag-handle")).toBeNull();
  });
});

describe("PlotPlotlineNode focus toggle (ADR-0053 §6)", () => {
  it("toggles focus for this thread when the eye is pressed", async () => {
    const focused: string[] = [];
    fakeActions({ expandedId: null, toggleFocus: (id) => focused.push(id) }).mount();
    const eye = screen.getByRole("button", { name: "Focus this thread" });
    expect(eye.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(eye);
    expect(focused).toEqual(["line_1"]);
  });

  it("shows the eye as active when this thread is the focused one", () => {
    fakeActions({ expandedId: null, focusedId: "line_1" }).mount();
    const eye = screen.getByRole("button", { name: "Clear focus" });
    expect(eye.getAttribute("aria-pressed")).toBe("true");
    expect(eye.classList.contains("active")).toBe(true);
  });

  it("offers no focus control without an actions context (the mount-test degrade)", () => {
    render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    expect(screen.queryByRole("button", { name: "Focus this thread" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear focus" })).toBeNull();
  });
});

describe("PlotPlotlineNode on-node editing (ADR-0053 §3)", () => {
  it("does not expand when its id isn't the board's expanded one", () => {
    fakeActions({ expandedId: null }).mount();
    expect(screen.queryByPlaceholderText("Plotline name")).toBeNull();
    // Read-only roster still shows.
    expect(screen.getByText("Setup")).toBeTruthy();
  });

  it("expands into an editor that loads the plotline's name and beats", async () => {
    fakeActions().mount();
    // The name loads from the full entry, and each beat is the section's title input.
    const name = await screen.findByPlaceholderText("Plotline name");
    expect((name as HTMLInputElement).value).toBe("Main plot");
    const beatInputs = screen.getAllByRole("textbox", { name: /Specialized beats \d+ title/ }) as HTMLInputElement[];
    expect(beatInputs.map((i) => i.value)).toEqual(["Setup", "Confrontation"]);
  });

  it("renaming the plotline saves the edited entry", async () => {
    const { saved } = fakeActions().mount();
    const name = (await screen.findByPlaceholderText("Plotline name")) as HTMLInputElement;
    await fireEvent.input(name, { target: { value: "Romance" } });
    await fireEvent.blur(name);
    await waitFor(() => expect(saved.length).toBe(1));
    expect(saved[0].title).toBe("Romance");
  });

  it("adding a beat saves a roster with the new beat appended", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Plotline name");
    await fireEvent.click(screen.getByRole("button", { name: "+ Add item" }));
    // The section save is debounced (SECTION_SAVE_DEBOUNCE_MS).
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 2000 });
    const beats = saved[0].metadata.instance_beats as Array<Record<string, unknown>>;
    expect(beats).toHaveLength(3);
    expect(beats[0].title).toBe("Setup");
    expect(beats[1].title).toBe("Confrontation");
    expect(beats[2]).toEqual({});
  });

  it("a beat title edit saves the roster with the new title and the beat's other members intact", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Plotline name");
    const input = screen.getByRole("textbox", { name: "Specialized beats 1 title" }) as HTMLInputElement;
    await fireEvent.change(input, { target: { value: "Renamed setup" } });
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 2000 });
    const beats = saved[0].metadata.instance_beats as Array<Record<string, unknown>>;
    expect(beats[0]).toEqual({
      title: "Renamed setup",
      function: "",
      guidance: "",
      specifics: "",
      required: true,
      id: "b1",
    });
  });

  it("emptying the name reverts instead of saving an invalid empty title", async () => {
    const { saved } = fakeActions().mount();
    const name = (await screen.findByPlaceholderText("Plotline name")) as HTMLInputElement;
    await fireEvent.input(name, { target: { value: "   " } });
    await fireEvent.blur(name);
    // Reverted to the last-good title (data.title); nothing saved.
    await waitFor(() => expect(name.value).toBe("Main plot"));
    expect(saved).toHaveLength(0);
  });

  it("the expanded editor offers Delete plotline, which calls onDelete", async () => {
    const { deleted } = fakeActions().mount();
    const del = await screen.findByRole("button", { name: "Delete plotline" });
    await fireEvent.click(del);
    expect(deleted).toEqual(["line_1"]);
  });

  it("the expanded editor offers Open in editor (the escape hatch), which calls onOpenInEditor", async () => {
    const opened: string[] = [];
    fakeActions({ onOpenInEditor: (id) => opened.push(id) }).mount();
    const open = await screen.findByRole("button", { name: "Open in editor" });
    await fireEvent.click(open);
    expect(opened).toEqual(["line_1"]);
  });

  it("hides Open in editor when the host provides no onOpenInEditor (optional action)", async () => {
    fakeActions().mount(); // default fakeActions omits onOpenInEditor
    await screen.findByPlaceholderText("Plotline name"); // wait for the editor to expand
    expect(screen.queryByRole("button", { name: "Open in editor" })).toBeNull();
  });

  it("stamps the backend-minted id of a new beat onto the draft, so the next save carries it", async () => {
    // The fake save mints an id for any beat without one (what the backend does).
    const flushed: Array<{ revision: string; metadata: Record<string, unknown> }> = [];
    fakeActions({
      save: async (e) => {
        flushed.push(e);
        const beats = (e.metadata.instance_beats as Array<Record<string, MetadataValue>>).map((b, i) =>
          typeof b.id === "string" && b.id ? b : { ...b, id: `minted_${i}` },
        );
        return { ...e, revision: `r${flushed.length + 1}`, metadata: { ...e.metadata, instance_beats: beats } };
      },
    }).mount();
    await screen.findByPlaceholderText("Plotline name");
    await fireEvent.click(screen.getByRole("button", { name: "+ Add item" }));
    await waitFor(() => expect(flushed.length).toBe(1), { timeout: 2000 });
    expect((flushed[0].metadata.instance_beats as unknown[])[2]).toEqual({});
    // A later edit to that beat sends the stamped id back, not a blank the backend would
    // re-mint, over the revision the first save advanced to.
    const input = screen.getByRole("textbox", { name: "Specialized beats 3 title" });
    await fireEvent.change(input, { target: { value: "Payoff" } });
    await waitFor(() => expect(flushed.length).toBe(2), { timeout: 2000 });
    expect((flushed[1].metadata.instance_beats as unknown[])[2]).toEqual({ title: "Payoff", id: "minted_2" });
    expect(flushed[1].revision).toBe("r2");
  });

  it("removing a beat saves the shortened roster", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Plotline name");
    await fireEvent.click(screen.getByRole("button", { name: "Remove item 1" }));
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 2000 });
    const beats = saved[0].metadata.instance_beats as Array<{ title: string }>;
    expect(beats.map((b) => b.title)).toEqual(["Confrontation"]);
  });
});

// The header kebab (#1096) surfaces Delete / Open-in-editor on the COLLAPSED node, so
// they no longer require the expand-and-scroll the foot-actions do. Tested collapsed
// (expandedId: null) so the only such buttons come from the kebab, not the foot-actions.
describe("PlotPlotlineNode actions kebab (#1096)", () => {
  it("surfaces Delete without expanding — the kebab's Delete calls onDelete", async () => {
    const { deleted } = fakeActions({ expandedId: null }).mount();
    expect(screen.queryByRole("button", { name: "Delete plotline" })).toBeNull(); // collapsed: no foot-actions
    await fireEvent.click(screen.getByRole("button", { name: "Plotline actions" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Delete plotline" }));
    expect(deleted).toEqual(["line_1"]);
  });

  it("surfaces Open in editor in the kebab when the host provides onOpenInEditor", async () => {
    const opened: string[] = [];
    fakeActions({ expandedId: null, onOpenInEditor: (id) => opened.push(id) }).mount();
    await fireEvent.click(screen.getByRole("button", { name: "Plotline actions" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Open in editor" }));
    expect(opened).toEqual(["line_1"]);
  });

  it("omits the kebab's Open in editor when the host provides none (optional action)", async () => {
    fakeActions({ expandedId: null }).mount(); // default omits onOpenInEditor
    await fireEvent.click(screen.getByRole("button", { name: "Plotline actions" }));
    expect(screen.queryByRole("menuitem", { name: "Open in editor" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Delete plotline" })).toBeTruthy();
  });

  it("offers no kebab without an actions context (the read-only mount degrade)", () => {
    render(PlotPlotlineNode, { props: { id: "line_1", data: data() } });
    expect(screen.queryByRole("button", { name: "Plotline actions" })).toBeNull();
  });
});
