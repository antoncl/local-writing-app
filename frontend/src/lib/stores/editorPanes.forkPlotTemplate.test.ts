// forkPlotTemplate clone (ADR-0048 S4c, generalized from ADR-0049 §5). Cloning a
// Library/ancestor plot template mints a NEW id and leaves the shipped original
// in place — the same clone-to-own gesture as prompts, so there is no in-place
// reconcile; the fresh editable copy is opened in its own pane.
//
// What these tests pin: forkPlotTemplate clones via the API, then opens the
// returned copy (its new id, not the shipped original's), and only after the
// clone exists.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { api } from "@/lib/api";
import type { PlotTemplate } from "@/lib/types";

const LIBRARY: PlotTemplate = {
  id: "builtin-plot-three-act-story-arc",
  title: "Three-Act Story Arc",
  body: "shipped guide",
  revision: "",
  entry_type: "plot:template",
  template: { slug: "three-act-story-arc", display_name: "Three-Act Story Arc" },
  metadata: {},
  computed_metadata: {},
  source_layer_id: "layer_library",
  source_layer_label: "Library",
  is_library: true,
};

const CLONE: PlotTemplate = {
  ...LIBRARY,
  id: "plot_new",
  revision: "r1",
  source_layer_id: "layer_project",
  source_layer_label: "",
  is_library: false,
};

describe("editorPanes.forkPlotTemplate (ADR-0048 S4c clone)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
    // refreshPlotTemplates() runs inside forkPlotTemplate; keep it off the network.
    vi.spyOn(api, "listPlotTemplates").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "forkPlotTemplate").mockResolvedValue(CLONE);
  });

  afterEach(() => editorPanes.reset());

  it("clones the Library template and opens the new copy (its new id)", async () => {
    const open = vi.spyOn(editorPanes, "openPlotTemplate").mockResolvedValue(undefined);

    await editorPanes.forkPlotTemplate(LIBRARY.id);

    expect(api.forkPlotTemplate).toHaveBeenCalledWith(LIBRARY.id);
    // Opens the fresh copy, not the shipped original.
    expect(open).toHaveBeenCalledWith(CLONE.id);
    expect(open).not.toHaveBeenCalledWith(LIBRARY.id);
    // The clone must exist before we try to open it.
    expect(
      (api.forkPlotTemplate as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0],
    ).toBeLessThan((open as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0]);
  });
});
