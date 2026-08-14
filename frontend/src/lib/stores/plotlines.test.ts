// Plotlines store undo substrate (ADR-0053 §7, #902) — the plotline twins of the
// card capture/restore/recreate helpers. A plotline restore refreshes BOTH the roster
// and the board (its colour/beats feed cards' tint + badges), unlike a card's board-only
// refresh; these tests pin that shape and the fetch-fresh / create-then-PUT behaviour.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { plotlineStateOf, getPlotlineState, restorePlotlineState, recreatePlotline } from "./plotlines";
import type { PlotlineEntry, PlotBoardProjection } from "@/lib/types";

const plotline = (metadata: PlotlineEntry["metadata"] = {}): PlotlineEntry => ({
  id: "p1",
  title: "The sister arc",
  body: "",
  revision: "pr1",
  entry_type: "plot:plotline",
  metadata,
  computed_metadata: {},
});

const projection = (): PlotBoardProjection => ({
  board_id: "b",
  board_revision: "r",
  layout: {},
  plotlines: [],
  containers: [],
  cards: [],
});

afterEach(() => vi.restoreAllMocks());

describe("plotlines undo substrate", () => {
  it("plotlineStateOf deep-copies metadata (colour + beats + lineage)", () => {
    const live = plotline({ color: "rose", instance_beats: [{ beat_id: "b1", title: "Meet" }] });
    const snap = plotlineStateOf(live);
    (live.metadata.instance_beats as unknown[]).push({ beat_id: "b2", title: "Part" });
    expect(snap.metadata.instance_beats).toEqual([{ beat_id: "b1", title: "Meet" }]);
  });

  it("getPlotlineState reads the whole authored state", async () => {
    vi.spyOn(api, "getPlotline").mockResolvedValue({ ...plotline({ color: "moss" }), body: "A thread." });
    expect(await getPlotlineState("p1")).toEqual({ title: "The sister arc", body: "A thread.", metadata: { color: "moss" } });
  });

  it("restorePlotlineState fetches fresh then saves; refreshes roster + board", async () => {
    const getP = vi.spyOn(api, "getPlotline").mockResolvedValue({ ...plotline({ color: "new" }), revision: "pr9" });
    const save = vi.spyOn(api, "savePlotline").mockImplementation((e) => Promise.resolve(e));
    const roster = vi.spyOn(api, "listPlotlines").mockResolvedValue({ entries: [] });
    const board = vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await restorePlotlineState("p1", { title: "Old", body: "Was.", metadata: { color: "rose" } });
    expect(getP).toHaveBeenCalledWith("p1");
    expect(save.mock.calls[0][0].revision).toBe("pr9"); // the live revision, not the snapshot's
    expect(save.mock.calls[0][0].metadata).toEqual({ color: "rose" });
    expect(save.mock.calls[0][1]).toBe("Was.");
    expect(roster).toHaveBeenCalledTimes(1);
    expect(board).toHaveBeenCalledTimes(1);
  });

  it("recreatePlotline creates under the supplied id, then restores beats + lineage", async () => {
    const create = vi.spyOn(api, "createPlotline").mockResolvedValue(plotline());
    vi.spyOn(api, "getPlotline").mockResolvedValue(plotline());
    const save = vi.spyOn(api, "savePlotline").mockImplementation((e) => Promise.resolve(e));
    vi.spyOn(api, "listPlotlines").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "getPlotBoardProjection").mockResolvedValue(projection());
    await recreatePlotline("p1", {
      title: "Restored",
      body: "Back.",
      metadata: { color: "rose", source_template_id: "tpl1", instance_beats: [{ beat_id: "b1", title: "Meet" }] },
    });
    expect(create).toHaveBeenCalledWith("Restored", "p1");
    expect(save.mock.calls[0][0].metadata).toEqual({
      color: "rose",
      source_template_id: "tpl1",
      instance_beats: [{ beat_id: "b1", title: "Meet" }],
    });
  });
});
