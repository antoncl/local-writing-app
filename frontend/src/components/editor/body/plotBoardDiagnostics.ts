import type { PlotBoardCard, PlotPointClaim } from "@/lib/types";

export type PlotDiagnosticSeverity = "warning" | "info";

export type PlotDiagnostic = {
  key: string;
  label: string;
  severity: PlotDiagnosticSeverity;
};

export type PlotDiagnosticSummary = {
  total: number;
  untaggedCards: number;
  unsupportedClaims: number;
  weakClaims: number;
  unclaimedBeats: number;
  unsatisfiedBeats: number;
  overloadedCards: number;
};

export type PlotDiagnostics = {
  summary: PlotDiagnosticSummary;
  cards: Map<string, PlotDiagnostic[]>;
  claims: Map<string, PlotDiagnostic[]>;
  points: Map<string, PlotDiagnostic[]>;
};

type DiagnosticPointRow = {
  instance: { id: string };
  point: { plot_point_id: string };
  claims: PlotPointClaim[];
};

const OVERLOADED_CLAIM_COUNT = 4;

export function pointDiagnosticKey(instanceId: string, pointId: string): string {
  return `${instanceId}:${pointId}`;
}

function hasEvidence(claim: PlotPointClaim): boolean {
  return Boolean(claim.rationale?.trim() || claim.evidence?.trim());
}

function add(map: Map<string, PlotDiagnostic[]>, id: string, diagnostic: PlotDiagnostic): void {
  const list = map.get(id) ?? [];
  list.push(diagnostic);
  map.set(id, list);
}

export function buildPlotDiagnostics(
  cards: PlotBoardCard[],
  claims: PlotPointClaim[],
  paletteRows: DiagnosticPointRow[],
): PlotDiagnostics {
  const diagnostics: PlotDiagnostics = {
    summary: {
      total: 0,
      untaggedCards: 0,
      unsupportedClaims: 0,
      weakClaims: 0,
      unclaimedBeats: 0,
      unsatisfiedBeats: 0,
      overloadedCards: 0,
    },
    cards: new Map(),
    claims: new Map(),
    points: new Map(),
  };
  const claimsByCard = new Map<string, PlotPointClaim[]>();
  for (const claim of claims) {
    const list = claimsByCard.get(claim.card_id) ?? [];
    list.push(claim);
    claimsByCard.set(claim.card_id, list);
    if (!hasEvidence(claim)) {
      diagnostics.summary.unsupportedClaims += 1;
      add(diagnostics.claims, claim.id, { key: "unsupported", label: "No rationale or evidence", severity: "warning" });
    }
    if (claim.strength === "weak") {
      diagnostics.summary.weakClaims += 1;
      add(diagnostics.claims, claim.id, { key: "weak", label: "Marked weak", severity: "warning" });
    }
  }
  for (const card of cards) {
    const cardClaims = claimsByCard.get(card.id) ?? [];
    if (cardClaims.length === 0) {
      diagnostics.summary.untaggedCards += 1;
      add(diagnostics.cards, card.id, { key: "untagged", label: "No story markers", severity: "warning" });
    }
    if (cardClaims.length >= OVERLOADED_CLAIM_COUNT) {
      diagnostics.summary.overloadedCards += 1;
      add(diagnostics.cards, card.id, { key: "overloaded", label: `${cardClaims.length} story markers`, severity: "info" });
    }
  }
  for (const row of paletteRows) {
    const key = pointDiagnosticKey(row.instance.id, row.point.plot_point_id);
    if (row.claims.length === 0) {
      diagnostics.summary.unclaimedBeats += 1;
      add(diagnostics.points, key, { key: "unclaimed", label: "No supporting cards", severity: "warning" });
    } else if (!row.claims.some((claim) => claim.claim_type === "satisfies")) {
      diagnostics.summary.unsatisfiedBeats += 1;
      add(diagnostics.points, key, { key: "unsatisfied", label: "No card clearly earns this", severity: "warning" });
    }
  }
  diagnostics.summary.total =
    diagnostics.summary.untaggedCards +
    diagnostics.summary.unsupportedClaims +
    diagnostics.summary.weakClaims +
    diagnostics.summary.unclaimedBeats +
    diagnostics.summary.unsatisfiedBeats +
    diagnostics.summary.overloadedCards;
  return diagnostics;
}
