import { describe, expect, it } from "vitest";
import type { LoreFit } from "@/lib/types";
import {
  declaredOverBudget,
  declaredOverLine,
  lastReportedTurn,
  leftOutSegment,
  loreSourceLabel,
} from "./loreFit";

const FIT: LoreFit = { budget_tokens: 16000, used_tokens: 15800, declared_tokens: 2100, kept: 21, left_out: [] };

describe("loreFit", () => {
  it("words the fit the way the ADR mockup reads", () => {
    expect(leftOutSegment({ ...FIT, left_out: Array(19).fill({ id: "x", title: "", source: "structural_hop", tokens: 1 }) }))
      .toBe("lore 15.8k/16k · 19 left out");
    expect(declaredOverLine({ ...FIT, declared_tokens: 30200 })).toBe("declared lore 30.2k, over the 16k budget");
  });

  it("treats a budget of 0 as declared-only, never over", () => {
    expect(declaredOverBudget({ ...FIT, declared_tokens: 30200 })).toBe(true);
    expect(declaredOverBudget({ ...FIT, declared_tokens: 100 })).toBe(false);
    expect(declaredOverBudget({ ...FIT, budget_tokens: 0, declared_tokens: 30200 })).toBe(false);
  });

  it("labels every source and passes an unknown one through", () => {
    expect(loreSourceLabel("depth1_expansion")).toBe("one hop · mention");
    expect(loreSourceLabel("structural_hop")).toBe("one hop · link");
    expect(loreSourceLabel("elsewhere")).toBe("elsewhere");
  });

  it("finds the last assistant turn that carries a report, past a stopped or streaming one", () => {
    const history = [
      { role: "user", content: "a" },
      { role: "assistant", content: "b", lore_fit: FIT },
      { role: "user", content: "c" },
      { role: "assistant", content: "partial…", stopped: true },
      { role: "assistant", content: "", lore_fit: null },
    ];
    expect(lastReportedTurn(history)).toBe(history[1]);
    expect(lastReportedTurn([{ role: "user", content: "a" }])).toBeNull();
  });
});
