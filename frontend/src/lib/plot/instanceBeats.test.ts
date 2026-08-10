// Shared arc-beats reader (ADR-0048 S7) — used by the arc rail and the beat picker.
import { describe, expect, it } from "vitest";
import { instanceBeats } from "./instanceBeats";
import type { TemplateInstanceSummary } from "@/lib/types";

const arc = (instance_beats: unknown): TemplateInstanceSummary =>
  ({ id: "i1", title: "Arc", body: "", entry_type: "plot:template_instance", metadata: { instance_beats } }) as unknown as TemplateInstanceSummary;

describe("instanceBeats", () => {
  it("returns the beats list", () => {
    expect(instanceBeats(arc([{ id: "b1", title: "One" }]))).toEqual([{ id: "b1", title: "One" }]);
  });

  it("returns [] when instance_beats is missing or not a list", () => {
    expect(instanceBeats(arc(undefined))).toEqual([]);
    expect(instanceBeats(arc("nope"))).toEqual([]);
    expect(instanceBeats({ id: "i1", title: "Arc", body: "", entry_type: "plot:template_instance", metadata: {} } as TemplateInstanceSummary)).toEqual([]);
  });
});
