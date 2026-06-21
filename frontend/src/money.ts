// Display-currency helper. Backend stores AI cost in USD (provider
// billing currency); the UI shows EUR. Single conversion + format
// helper here so the rate change is one edit.
//
// See `decisions_currency_display` in memory for rationale.

// Hardcoded rate for v1. Revisit (probably as a user setting or a
// periodic fetch) only if drift becomes a complaint. As of 2026-06,
// 1 USD ≈ 0.92 EUR.
const USD_TO_EUR = 0.92;

export function usdToEur(usd: number): number {
  return usd * USD_TO_EUR;
}

// Format a USD cost as a EUR string. Used everywhere a cost surfaces
// in the UI. Tiny costs (< 0.01) get more precision so users can see
// the difference between 0.0003 and 0.0050.
//
// Returns "—" for null/undefined (no cost known: no pricing data,
// or no assistant bound).
export function formatCostEur(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) {
    return "—";
  }
  const eur = usdToEur(usd);
  if (eur === 0) {
    return "€0.00";
  }
  if (Math.abs(eur) < 0.01) {
    // Sub-cent: 4 decimal places.
    return `€${eur.toFixed(4)}`;
  }
  if (Math.abs(eur) < 1) {
    // Sub-euro: 3 decimal places.
    return `€${eur.toFixed(3)}`;
  }
  // ≥ €1: 2 decimal places.
  return `€${eur.toFixed(2)}`;
}

// Compact token count: 1234 → "1.2k", 12345 → "12k", 1234567 → "1.2M".
export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n <= 0) {
    return "0";
  }
  if (n < 1000) {
    return String(n);
  }
  if (n < 10_000) {
    return `${(n / 1000).toFixed(1)}k`;
  }
  if (n < 1_000_000) {
    return `${Math.round(n / 1000)}k`;
  }
  return `${(n / 1_000_000).toFixed(1)}M`;
}
