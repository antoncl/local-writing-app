import { describe, expect, it } from "vitest";
import type { HistoryFit } from "@/lib/types";
import { droppedRoundsSegment, historyFitSummary } from "./historyFit";

const FIT: HistoryFit = { budget_tokens: 16000, used_tokens: 12400, kept_rounds: 4, dropped_rounds: 3 };

describe("historyFit", () => {
  it("words the segment as used/budget plus a drop count", () => {
    expect(droppedRoundsSegment(FIT)).toBe("history 12.4k/16k · 3 earlier exchanges dropped");
    expect(historyFitSummary(FIT)).toBe("history 12.4k/16k");
  });

  it("singularizes a single dropped exchange", () => {
    expect(droppedRoundsSegment({ ...FIT, dropped_rounds: 1 })).toBe("history 12.4k/16k · 1 earlier exchange dropped");
  });
});
