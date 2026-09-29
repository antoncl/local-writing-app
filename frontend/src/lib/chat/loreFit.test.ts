import { describe, expect, it } from "vitest";
import type { ChatSessionJournalEntry, LoreFit } from "@/lib/types";
import {
  declaredOverBudget,
  declaredOverLine,
  lastReportedTurn,
  leftOutSegment,
  loreSourceLabel,
  notSentKind,
  notSentReason,
  reachSkipped,
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

  it("gives a not-sent reason for a budget-dropped entry", () => {
    const entry: ChatSessionJournalEntry = { entry_id: "x", source: "depth1_expansion" };
    const fit: LoreFit = {
      ...FIT,
      left_out: [{ id: "x", title: "Nimitz", source: "depth1_expansion", tokens: 500 }],
    };
    expect(notSentReason(fit, entry)).toMatch(/over the lore budget/);
  });

  it("gives a not-sent reason for a hop entry under Named-only reach", () => {
    const entry: ChatSessionJournalEntry = { entry_id: "x", source: "depth1_expansion" };
    expect(notSentReason({ ...FIT, expansion: "named" }, entry))
      .toBe("Noticed, but not sent: this assistant's Lore reach is Named only.");
  });

  it("stays null for Named-only reach on a non-hop source", () => {
    const entry: ChatSessionJournalEntry = { entry_id: "x", source: "user_message" };
    expect(notSentReason({ ...FIT, expansion: "named" }, entry)).toBeNull();
  });

  it("stays null for a hop source when reach isn't Named-only", () => {
    const entry: ChatSessionJournalEntry = { entry_id: "x", source: "depth1_expansion" };
    expect(notSentReason({ ...FIT, expansion: "one_hop" }, entry)).toBeNull();
    expect(notSentReason(FIT, entry)).toBeNull();
  });
});

// #2341: the reason as a KIND (so the UI can mark each differently), and the
// entries a Named-only turn did not follow.
describe("notSentKind / reachSkipped (#2341)", () => {
  const fit = (over: Partial<LoreFit> = {}): LoreFit => ({
    budget_tokens: 1000,
    used_tokens: 900,
    declared_tokens: 0,
    kept: 1,
    left_out: [],
    ...over,
  });
  const j = (entry_id: string, source?: string) =>
    ({ entry_id, title: entry_id, source }) as ChatSessionJournalEntry;

  it("names the budget when the entry is in left_out, else reach for a Named-only hop", () => {
    const named = fit({ expansion: "named", left_out: [{ id: "a", title: "a", source: "user_message", tokens: 5 }] });
    expect(notSentKind(named, j("a", "user_message"))).toBe("budget");
    expect(notSentKind(named, j("b", "depth1_expansion"))).toBe("reach");
    expect(notSentKind(named, j("c", "user_message"))).toBeNull();
    expect(notSentKind(fit({ expansion: "one_hop" }), j("b", "depth1_expansion"))).toBeNull();
  });

  it("lists Named-only hops not followed: once each, never a promoted or budget-dropped one", () => {
    const f = fit({ expansion: "named", left_out: [{ id: "dropped", title: "d", source: "depth1_expansion", tokens: 5 }] });
    const journal = [
      j("hop", "depth1_expansion"),
      j("hop", "depth1_expansion"),
      j("promoted", "depth1_expansion"),
      j("promoted", "user_message"),
      j("dropped", "depth1_expansion"),
      j("named"),
    ];
    expect(reachSkipped(f, journal).map((e) => e.entry_id)).toEqual(["hop"]);
    expect(reachSkipped(fit({ expansion: "one_hop" }), journal)).toEqual([]);
  });
});
