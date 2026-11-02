// @vitest-environment happy-dom
// The card-height estimate reads the text scale the card's CSS uses: the root's
// `--ui-scale` (#2362). The pure maths is pinned in plotBoardLayout.test.ts.
import { afterEach, describe, expect, it } from "vitest";
import { boardTextScale, estCardHeight } from "./boardGeometry";

describe("boardTextScale (#2362)", () => {
  afterEach(() => {
    document.documentElement.style.removeProperty("--ui-scale");
  });

  it("reads the root's --ui-scale, which the default estimate then uses", () => {
    document.documentElement.style.setProperty("--ui-scale", "1.5");
    expect(boardTextScale()).toBe(1.5);
    expect(estCardHeight("t", "s", 2)).toBe(estCardHeight("t", "s", 2, 1.5));
    expect(estCardHeight("t", "s", 2)).toBeGreaterThan(estCardHeight("t", "s", 2, 1));
  });

  it("is 1 when the root carries no scale, or a value that isn't a positive number", () => {
    expect(boardTextScale()).toBe(1);
    document.documentElement.style.setProperty("--ui-scale", "nonsense");
    expect(boardTextScale()).toBe(1);
  });
});
