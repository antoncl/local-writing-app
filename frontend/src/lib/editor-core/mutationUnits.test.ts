import { describe, expect, it } from "vitest";
import { laterAppendCount, laterAppendNote } from "./mutationUnits";
import type { MutationMarkerRecord } from "@/lib/types";

const rec = (marker_id: string) => ({ marker_id }) as unknown as MutationMarkerRecord;

describe("laterAppendCount (#73)", () => {
  it("unions across records and drops the records' own ids", () => {
    const later = { a: ["x", "y"], b: ["y", "a", "z"] };
    expect(laterAppendCount([rec("a"), rec("b")], later)).toBe(3);
    expect(laterAppendCount([rec("a")], later)).toBe(2);
  });
  it("is 0 with nothing recorded", () => {
    expect(laterAppendCount([rec("a")], {})).toBe(0);
  });
});

describe("laterAppendNote (#73)", () => {
  it("words the singular, plural and empty cases", () => {
    expect(laterAppendNote(0)).toBe("");
    expect(laterAppendNote(1)).toBe("1 later append may lean on this text.");
    expect(laterAppendNote(2)).toBe("2 later appends may lean on this text.");
  });
});
