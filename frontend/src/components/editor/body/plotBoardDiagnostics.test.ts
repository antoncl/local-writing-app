import { describe, expect, it } from "vitest";
import { buildPlotDiagnostics, pointDiagnosticKey } from "./plotBoardDiagnostics";
import type { PlotBoardCard, PlotPointClaim } from "@/lib/types";

function card(id: string): PlotBoardCard {
  return { id, title: id } as PlotBoardCard;
}

function claim(patch: Partial<PlotPointClaim>): PlotPointClaim {
  return {
    id: "claim",
    card_id: "card",
    template_instance_id: "template",
    plot_point_id: "beat",
    claim_type: "satisfies",
    metadata: {},
    ...patch,
  } as PlotPointClaim;
}

describe("buildPlotDiagnostics", () => {
  it("flags cards, claims, and plot beats that need story-function attention", () => {
    const claims = [
      claim({ id: "weak", card_id: "a", strength: "weak", rationale: "thin" }),
      claim({ id: "unsupported", card_id: "a", plot_point_id: "partial", claim_type: "partially_satisfies" }),
      claim({ id: "one", card_id: "loaded", plot_point_id: "loaded_1", rationale: "a" }),
      claim({ id: "two", card_id: "loaded", plot_point_id: "loaded_2", rationale: "b" }),
      claim({ id: "three", card_id: "loaded", plot_point_id: "loaded_3", rationale: "c" }),
      claim({ id: "four", card_id: "loaded", plot_point_id: "loaded_4", rationale: "d" }),
    ];
    const diagnostics = buildPlotDiagnostics(
      [card("a"), card("untagged"), card("loaded")],
      claims,
      [
        { instance: { id: "template" }, point: { plot_point_id: "beat" }, claims: [claims[0]] },
        { instance: { id: "template" }, point: { plot_point_id: "missing" }, claims: [] },
        { instance: { id: "template" }, point: { plot_point_id: "partial" }, claims: [claims[1]] },
      ],
    );

    expect(diagnostics.cards.get("untagged")?.map((item) => item.key)).toEqual(["untagged"]);
    expect(diagnostics.cards.get("loaded")?.map((item) => item.key)).toEqual(["overloaded"]);
    expect(diagnostics.claims.get("weak")?.map((item) => item.key)).toEqual(["weak"]);
    expect(diagnostics.claims.get("unsupported")?.map((item) => item.key)).toEqual(["unsupported"]);
    expect(diagnostics.points.get(pointDiagnosticKey("template", "missing"))?.map((item) => item.key)).toEqual(["unclaimed"]);
    expect(diagnostics.points.get(pointDiagnosticKey("template", "partial"))?.map((item) => item.key)).toEqual(["unsatisfied"]);
    expect(diagnostics.summary.total).toBe(6);
  });
});
