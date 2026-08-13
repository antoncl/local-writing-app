// @vitest-environment happy-dom
// PlotPlotlineNode RENDER guard (ADR-0053 §3). A plotline is a first-class board node
// that must DISPLAY its beat roster, so — like PlotCardNode — a mount test asserts the
// content renders ([[reference_component_test_harness]]). The node imports nothing from
// @xyflow/svelte, so it mounts here on its own (the SvelteFlow canvas is not headless).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { waitFor } from "@testing-library/svelte";
import PlotPlotlineNode from "./PlotPlotlineNode.svelte";
import type { PlotPlotlineData } from "@/lib/plot/plotBoardLayout";
import { PLOT_PLOTLINE_ACTIONS, type PlotPlotlineActions } from "./plotPlotlineActions";
import { PLOT_DND_MIME } from "@/lib/plot/plotDnd";
import type { PlotlineEntry } from "@/lib/types";

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
    // No editor: the roster shows as text, not inputs, and there's no Add-beat control.
    expect(screen.queryByPlaceholderText("Plotline name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add beat" })).toBeNull();
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

  it("does not make beats draggable without a node id (the mount-test degrade)", () => {
    render(PlotPlotlineNode, { props: { data: data() } }); // no id
    const beats = screen.getAllByRole("listitem");
    expect(beats.every((li) => li.getAttribute("draggable") !== "true")).toBe(true);
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
    // The name loads from the full entry, and each beat is an editable title input.
    const name = await screen.findByPlaceholderText("Plotline name");
    expect((name as HTMLInputElement).value).toBe("Main plot");
    const beatInputs = screen.getAllByPlaceholderText("Beat title") as HTMLInputElement[];
    expect(beatInputs.map((i) => i.value)).toEqual(["Setup", "Confrontation"]);
    expect(screen.getByRole("button", { name: "Add beat" })).toBeTruthy();
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
    await fireEvent.click(screen.getByRole("button", { name: "Add beat" }));
    await waitFor(() => expect(saved.length).toBe(1));
    const beats = saved[0].metadata.instance_beats as Array<{ title: string }>;
    expect(beats.map((b) => b.title)).toEqual(["Setup", "Confrontation", "New beat"]);
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

  it("removing a beat saves the shortened roster", async () => {
    const { saved } = fakeActions().mount();
    await screen.findByPlaceholderText("Plotline name");
    const removeButtons = screen.getAllByRole("button", { name: "Remove beat" });
    await fireEvent.click(removeButtons[0]);
    await waitFor(() => expect(saved.length).toBe(1));
    const beats = saved[0].metadata.instance_beats as Array<{ title: string }>;
    expect(beats.map((b) => b.title)).toEqual(["Confrontation"]);
  });
});
