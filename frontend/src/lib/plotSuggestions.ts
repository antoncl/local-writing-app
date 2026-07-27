export type PlotSuggestionKind =
  | "card_revision"
  | "claim_change"
  | "new_claim"
  | "relationship_change"
  | "scene_promotion"
  | "question"
  | "unknown";

export type PlotSuggestion = {
  kind: PlotSuggestionKind;
  target_card_id: string;
  target_claim_id: string;
  template_instance_id: string;
  plot_point_id: string;
  title: string;
  reason: string;
  proposed_change: string;
  evidence_to_add: string;
};

const PLACEHOLDER_FRAGMENTS = [
  "short label",
  "why this concrete change",
  "why this would strengthen",
  "specific board-level edit",
  "concrete evidence the card",
  "_if_known",
];

export function stripPlotSuggestions(text: string): string {
  return text.replace(/<plot_suggestions\b[^>]*>[\s\S]*?<\/plot_suggestions>/gi, "").trim();
}

export function parsePlotSuggestions(text: string): PlotSuggestion[] {
  const out: PlotSuggestion[] = [];
  for (const block of matchAll(text, /<plot_suggestions\b[^>]*>([\s\S]*?)<\/plot_suggestions>/gi)) {
    const body = block[1] ?? "";
    for (const suggestion of matchAll(body, /<suggestion\b([^>]*)>([\s\S]*?)<\/suggestion>/gi)) {
      const attrs = parseAttributes(suggestion[1] ?? "");
      const parsed: PlotSuggestion = {
        kind: normalizeKind(attrs.kind),
        target_card_id: cleanTarget(attrs.target_card_id),
        target_claim_id: cleanTarget(attrs.target_claim_id),
        template_instance_id: cleanTarget(attrs.template_instance_id),
        plot_point_id: cleanTarget(attrs.plot_point_id),
        title: extractTag(suggestion[2] ?? "", "title"),
        reason: extractTag(suggestion[2] ?? "", "reason"),
        proposed_change: extractTag(suggestion[2] ?? "", "proposed_change"),
        evidence_to_add: extractTag(suggestion[2] ?? "", "evidence_to_add"),
      };
      if (isConcreteSuggestion(parsed)) out.push(parsed);
    }
  }
  return out;
}

function parseAttributes(text: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const match of matchAll(text, /([A-Za-z_][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) {
    attrs[match[1]] = decodeXml(match[2] ?? match[3] ?? "");
  }
  return attrs;
}

function extractTag(text: string, tag: string): string {
  const pattern = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i");
  const match = pattern.exec(text);
  return normalizeText(match?.[1] ?? "");
}

function normalizeKind(kind: string | undefined): PlotSuggestionKind {
  const normalized = (kind ?? "").trim();
  switch (normalized) {
    case "card_revision":
    case "claim_change":
    case "new_claim":
    case "relationship_change":
    case "scene_promotion":
    case "question":
      return normalized;
    default:
      return "unknown";
  }
}

function cleanTarget(value: string | undefined): string {
  const cleaned = normalizeText(value ?? "");
  return cleaned.includes("_if_known") ? "" : cleaned;
}

function normalizeText(value: string): string {
  return decodeXml(value).replace(/\s+/g, " ").trim();
}

function decodeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function isConcreteSuggestion(suggestion: PlotSuggestion): boolean {
  const content = [
    suggestion.title,
    suggestion.reason,
    suggestion.proposed_change,
    suggestion.evidence_to_add,
  ].join(" ").toLowerCase();
  if (!content.trim()) return false;
  return !PLACEHOLDER_FRAGMENTS.some((fragment) => content.includes(fragment));
}

function matchAll(text: string, pattern: RegExp): RegExpMatchArray[] {
  return Array.from(text.matchAll(pattern));
}
