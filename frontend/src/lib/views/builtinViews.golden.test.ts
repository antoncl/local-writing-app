import { describe, expect, it } from "vitest";
import { builtinViews } from "./builtinViews";
import fixture from "./__fixtures__/builtin-extra-view-specs.json";

// The frontend `builtinViews` synthesizes the curated extra views for the pane
// switcher; the backend `_builtin_extra_view_spec` materializes the SAME views
// on the first UI-state write (#1682). Both assert this fixture — like the
// default-view golden — so the two hand-written builders can't silently drift
// (a drifted spec would make the pane's "Runnable prompts" and its materialized
// node select different rosters).
describe("builtin extra view golden (backend/frontend drift guard)", () => {
  const byId = new Map(
    ["prompt", "chat"].flatMap((kind) => builtinViews(kind).slice(1).map((v) => [v.id, v] as const)),
  );

  for (const [id, expected] of Object.entries(fixture)) {
    if (id === "_comment") continue;
    it(`${id} matches the canonical shape`, () => {
      const view = byId.get(id);
      expect(view).toBeDefined();
      expect({
        title: view!.title,
        expr: view!.spec.expr,
        sort_by: view!.spec.sort?.by,
      }).toEqual(expected);
    });
  }

  it("the fixture covers every shipped extra (a new extra must join the golden)", () => {
    const fixtureIds = Object.keys(fixture).filter((k) => k !== "_comment");
    expect([...byId.keys()].sort()).toEqual(fixtureIds.sort());
  });
});
