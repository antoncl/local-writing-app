import { describe, expect, it } from "vitest";
import { isNearBottom } from "./scrollAnchor";

describe("isNearBottom", () => {
  it("is true at exact bottom (distance 0)", () => {
    expect(isNearBottom(600, 1000, 400)).toBe(true);
  });

  it("is true within the threshold (distance 40 <= 48)", () => {
    expect(isNearBottom(560, 1000, 400)).toBe(true);
  });

  it("is false just past the threshold (distance 49 > 48)", () => {
    expect(isNearBottom(551, 1000, 400)).toBe(false);
  });

  it("is true when content is shorter than the viewport (negative distance)", () => {
    expect(isNearBottom(0, 300, 400)).toBe(true);
  });

  it("honors a custom threshold argument", () => {
    // distance = 1000 - 500 - 400 = 100; false at the default 48px threshold...
    expect(isNearBottom(500, 1000, 400)).toBe(false);
    // ...but true once the threshold is widened past the distance.
    expect(isNearBottom(500, 1000, 400, 120)).toBe(true);
  });
});
