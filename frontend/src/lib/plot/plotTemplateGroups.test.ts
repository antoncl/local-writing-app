import { describe, expect, it } from "vitest";
import { groupPlotTemplates } from "./plotTemplateGroups";
import type { PlotTemplateSummary } from "@/lib/types";

const tpl = (id: string, family?: string): PlotTemplateSummary =>
  ({
    id,
    title: id,
    body: "",
    entry_type: "plot:template",
    template: { slug: id, display_name: id, ...(family ? { family } : {}) },
    is_library: true,
  }) as PlotTemplateSummary;

describe("groupPlotTemplates", () => {
  it("routes each family to its bucket — every genre family, not just one", () => {
    const groups = groupPlotTemplates([
      tpl("act", "act"),
      tpl("journey", "journey"),
      tpl("cycle", "cycle"),
      tpl("puzzle", "puzzle"),
      tpl("genre", "genre"),
      tpl("relationship", "relationship"),
      tpl("arc", "character_arc"),
    ]);
    expect(groups.structures.map((e) => e.id)).toEqual(["act", "journey", "cycle"]);
    // All three genre-shaped families, so narrowing GENRE_FAMILIES would fail here.
    expect(groups.genre.map((e) => e.id)).toEqual(["puzzle", "genre", "relationship"]);
    expect(groups.arcs.map((e) => e.id)).toEqual(["arc"]);
  });

  it("falls a missing or unknown family through to structures (the catch-all)", () => {
    const groups = groupPlotTemplates([tpl("no-family"), tpl("custom", "custom"), tpl("future", "some_new_family")]);
    expect(groups.structures.map((e) => e.id)).toEqual(["no-family", "custom", "future"]);
    expect(groups.genre).toHaveLength(0);
    expect(groups.arcs).toHaveLength(0);
  });

  it("is disjoint and exhaustive — every entry lands in exactly one bucket, order preserved", () => {
    const entries = [tpl("a", "act"), tpl("m", "puzzle"), tpl("c", "character_arc"), tpl("t", "genre")];
    const groups = groupPlotTemplates(entries);
    expect(groups.structures.length + groups.genre.length + groups.arcs.length).toBe(entries.length);
    expect(groups.structures.map((e) => e.id)).toEqual(["a"]);
    expect(groups.genre.map((e) => e.id)).toEqual(["m", "t"]);
    expect(groups.arcs.map((e) => e.id)).toEqual(["c"]);
  });
});
