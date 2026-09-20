import { describe, expect, it } from "vitest";
import { withStampedBeatIds } from "./beatRoster";

describe("withStampedBeatIds", () => {
  it("fills a missing id positionally from the saved roster", () => {
    const current = [{ title: "Setup" }];
    const saved = [{ title: "Setup", id: "b1" }];
    expect(withStampedBeatIds(current, saved)).toEqual([{ title: "Setup", id: "b1" }]);
  });

  it("keeps an existing id untouched", () => {
    const current = [{ title: "Setup", id: "existing" }];
    const saved = [{ title: "Setup", id: "b1" }];
    expect(withStampedBeatIds(current, saved)).toBeNull();
  });

  it("returns null when every item already has an id", () => {
    const current = [{ title: "A", id: "a" }, { title: "B", id: "b" }];
    const saved = [{ title: "A", id: "a" }, { title: "B", id: "b" }];
    expect(withStampedBeatIds(current, saved)).toBeNull();
  });

  it("returns null when either argument is not an array", () => {
    expect(withStampedBeatIds(null, [{ title: "A" }])).toBeNull();
    expect(withStampedBeatIds([{ title: "A" }], null)).toBeNull();
    expect(withStampedBeatIds("not an array", "also not")).toBeNull();
  });

  it("leaves the tail untouched when saved is shorter than current", () => {
    const current = [{ title: "A" }, { title: "B" }];
    const saved = [{ title: "A", id: "a" }];
    expect(withStampedBeatIds(current, saved)).toEqual([{ title: "A", id: "a" }, { title: "B" }]);
  });
});
