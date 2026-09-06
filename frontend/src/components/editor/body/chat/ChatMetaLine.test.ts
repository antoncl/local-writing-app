// @vitest-environment happy-dom
// ChatMetaLine collapses the estimate + cache-TTL + session-cost readouts
// into one quiet metadata line (ADR-0076 S1) — a data-displaying surface, so
// it gets a mount test (#642) mirroring ChatTranscript.test.ts's harness.
import { describe, expect, it } from "vitest";
import { render } from "@/lib/test/component";
import ChatMetaLine from "./ChatMetaLine.svelte";
import { formatCostEur, formatTokens } from "@/lib/utils/money";
import type { TtlChip } from "./chatInputs";

const ESTIMATE = {
  tokens: 1500,
  cost_usd: 2,
  cached: null as boolean | null,
  warnings: [] as string[],
  cache_blocks: [],
};

function liveChip(overrides: Partial<TtlChip> = {}): TtlChip {
  return { slot: "system", label: "System", ttlLabel: "1h", formatted: "57m", expired: false, remainingSec: 3420, ...overrides };
}

describe("ChatMetaLine", () => {
  it("renders one line with the estimate and session terms", () => {
    const { container } = render(ChatMetaLine, { estimate: ESTIMATE, ttlChips: [], sessionCostUsd: 5 });
    expect(container.querySelectorAll(".cbv-meta-line").length).toBe(1);
    expect(container.textContent).toContain("next turn");
    expect(container.textContent).toContain(`~${formatTokens(ESTIMATE.tokens)} tok`);
    expect(container.textContent).toContain(formatCostEur(ESTIMATE.cost_usd));
    expect(container.textContent).toContain(`session ${formatCostEur(5)}`);
  });

  it("renders only the session term when estimate is null", () => {
    const { container } = render(ChatMetaLine, { estimate: null, ttlChips: [], sessionCostUsd: 5 });
    expect(container.textContent).not.toContain("next turn");
    expect(container.textContent).toContain(`session ${formatCostEur(5)}`);
  });

  it("renders nothing when both estimate and session cost are null", () => {
    const { container } = render(ChatMetaLine, { estimate: null, ttlChips: [], sessionCostUsd: null });
    expect(container.querySelector(".cbv-meta-line")).not.toBeInTheDocument();
  });

  it("renders a cache term for a live TTL chip under explicit caching", () => {
    const estimate = { ...ESTIMATE, cached: true };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [liveChip({ formatted: "57m" })],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache 57m");
    expect(container.querySelector(".cbv-meta-danger")).not.toBeInTheDocument();
  });

  it("renders 'cache expired' with the danger class when every chip has expired", () => {
    const estimate = { ...ESTIMATE, cached: true };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [liveChip({ expired: true, formatted: "expired", remainingSec: 0 })],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache expired");
    expect(container.querySelector(".cbv-meta-danger")).toBeInTheDocument();
  });

  it("renders 'cache expired' when ANY chip has expired — a live sibling must not mask a cold slot", () => {
    // system expired + lore live: the next send pays a cache re-write, so the
    // term must not read as warm (ADR-0076 S1 review).
    const estimate = { ...ESTIMATE, cached: true };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [
        liveChip({ expired: true, formatted: "expired", remainingSec: 0 }),
        liveChip({ slot: "lore", label: "Lore", ttlLabel: "5m", formatted: "4m", remainingSec: 240 }),
      ],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache expired");
    expect(container.textContent).not.toContain("cache 4m");
    expect(container.querySelector(".cbv-meta-danger")).toBeInTheDocument();
  });

  it("shows the soonest-to-evict chip by raw remaining time when all are live", () => {
    const estimate = { ...ESTIMATE, cached: true };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [
        liveChip({ formatted: "57m", remainingSec: 3420 }),
        liveChip({ slot: "lore", label: "Lore", ttlLabel: "5m", formatted: "4m", remainingSec: 240 }),
      ],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache 4m");
    expect(container.textContent).not.toContain("cache 57m");
  });

  it("renders no cache term when there are no chips", () => {
    const estimate = { ...ESTIMATE, cached: false };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [],
      sessionCostUsd: null,
    });
    expect(container.textContent).not.toContain("cache");
  });

  it("renders 'cached · no stated term' when cached and no term", () => {
    const estimate = {
      ...ESTIMATE,
      cached: true,
      cache_blocks: [{ label: "system", tokens: 10, tier: "stable", ttl_seconds: null }],
    };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cached · no stated term");
  });

  it("renders one line per soft-fail warning (#1544)", () => {
    const estimate = {
      ...ESTIMATE,
      warnings: [
        'Context pick "Arc tracker" is a saved view using `nest`, which the send path cannot evaluate — it contributed nothing.',
        "Context pick \"Scenes\" selects 'scene' nodes, which the send path cannot resolve — it contributed nothing.",
      ],
    };
    const { container } = render(ChatMetaLine, { estimate, ttlChips: [], sessionCostUsd: null });
    expect(container.querySelectorAll(".cbv-meta-warning").length).toBe(2);
    expect(container.textContent).toContain("Arc tracker");
    expect(container.textContent).toContain("'scene'");
    expect(container.querySelector(".cbv-meta-line")).toBeInTheDocument();
  });

  it("renders no warning block when the list is empty", () => {
    const { container } = render(ChatMetaLine, { estimate: ESTIMATE, ttlChips: [], sessionCostUsd: null });
    expect(container.querySelector(".cbv-meta-warnings")).not.toBeInTheDocument();
  });
});
