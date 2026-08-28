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
  caching_style: null as "none" | "auto" | "explicit" | null,
  cache_blocks: [],
};

function liveChip(overrides: Partial<TtlChip> = {}): TtlChip {
  return { slot: "system", label: "System", ttlLabel: "1h", formatted: "57m", expired: false, ...overrides };
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
    const estimate = { ...ESTIMATE, caching_style: "explicit" as const };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [liveChip({ formatted: "57m" })],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache 57m");
    expect(container.querySelector(".cbv-meta-danger")).not.toBeInTheDocument();
  });

  it("renders 'cache expired' with the danger class when every chip has expired", () => {
    const estimate = { ...ESTIMATE, caching_style: "explicit" as const };
    const { container } = render(ChatMetaLine, {
      estimate,
      ttlChips: [liveChip({ expired: true, formatted: "expired" })],
      sessionCostUsd: null,
    });
    expect(container.textContent).toContain("cache expired");
    expect(container.querySelector(".cbv-meta-danger")).toBeInTheDocument();
  });

  it("renders no cache term when caching_style is not explicit", () => {
    const { container } = render(ChatMetaLine, {
      estimate: ESTIMATE,
      ttlChips: [liveChip()],
      sessionCostUsd: null,
    });
    expect(container.textContent).not.toContain("cache");
  });
});
