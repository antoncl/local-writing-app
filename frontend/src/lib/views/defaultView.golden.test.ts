import { describe, expect, it } from "vitest";
import { defaultView } from "./evaluateView";
import fixture from "./__fixtures__/default-view-specs.json";

// The frontend `defaultView` is the canonical system-default-view shape. The backend
// `_default_view_spec` (which materializes the default on disk) MUST match it, or a
// pane looks one way before it's folded and another after. Both this test and
// backend/tests/test_views.py::test_default_view_specs_match_frontend assert the SAME
// fixture, so the two hand-written builders can't silently drift (#271 / review finding-2).
describe("system default view golden (backend/frontend drift guard)", () => {
  for (const [kind, expected] of Object.entries(fixture)) {
    if (kind === "_comment") continue;
    it(`${kind} default matches the canonical shape`, () => {
      const spec = defaultView(kind);
      expect({
        expr: spec.expr,
        // `params` joined the golden with #333 — the assistants default is the
        // first to declare a formal, and a formal that drifts between the two
        // builders means the pane's parameter strip appears or vanishes across
        // the first fold.
        params: spec.params ?? null,
        group_by: spec.group_by ?? null,
      }).toEqual(expected);
    });
  }
});
