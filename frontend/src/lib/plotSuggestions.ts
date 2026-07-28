export type PlotSuggestionKind =
  | "card_revision"
  | "beat_revision"
  | "claim_change"
  | "new_card"
  | "new_claim"
  | "relationship_change"
  | "scene_promotion"
  | "question"
  | "unknown";

export type PlotSuggestionBeatStatus =
  | "unplanned"
  | "planned"
  | "drafted"
  | "satisfied"
  | "intentionally_omitted";

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
  story_specifics: string;
  author_intent: string;
  expected_role: string;
  open_questions: string[];
  status: PlotSuggestionBeatStatus | "";
};

export type PlotSuggestionTarget = {
  label: string;
  value: string;
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
        story_specifics: extractTag(suggestion[2] ?? "", "story_specifics"),
        author_intent: extractTag(suggestion[2] ?? "", "author_intent"),
        expected_role: extractTag(suggestion[2] ?? "", "expected_role"),
        open_questions: extractTags(suggestion[2] ?? "", "open_question"),
        status: normalizeStatus(extractTag(suggestion[2] ?? "", "status")),
      };
      if (isConcreteSuggestion(parsed)) out.push(parsed);
    }
  }
  return out;
}

export function plotSuggestionClipboardText(
  suggestion: PlotSuggestion,
  field: "proposed_change" | "evidence_to_add",
): string {
  const label = field === "proposed_change" ? "Proposed change" : "Evidence to add";
  const lines = [
    suggestion.title,
    `${label}: ${suggestion[field]}`,
    suggestion.reason ? `Reason: ${suggestion.reason}` : "",
    suggestion.target_card_id ? `Card: ${suggestion.target_card_id}` : "",
    suggestion.target_claim_id ? `Story marker: ${suggestion.target_claim_id}` : "",
    suggestion.template_instance_id ? `Template: ${suggestion.template_instance_id}` : "",
    suggestion.plot_point_id ? `Story beat: ${suggestion.plot_point_id}` : "",
  ];
  return lines.filter(Boolean).join("\n");
}

export function plotSuggestionBeatClipboardText(suggestion: PlotSuggestion): string {
  const lines = [
    suggestion.title,
    suggestion.story_specifics ? `Story specifics: ${suggestion.story_specifics}` : "",
    suggestion.author_intent ? `Author intent: ${suggestion.author_intent}` : "",
    suggestion.expected_role ? `Expected role: ${suggestion.expected_role}` : "",
    ...suggestion.open_questions.map((question) => `Open question: ${question}`),
    suggestion.status ? `Status: ${suggestion.status}` : "",
    suggestion.reason ? `Reason: ${suggestion.reason}` : "",
    suggestion.template_instance_id ? `Template: ${suggestion.template_instance_id}` : "",
    suggestion.plot_point_id ? `Story beat: ${suggestion.plot_point_id}` : "",
  ];
  return lines.filter(Boolean).join("\n");
}

export function plotSuggestionQuestionClipboardText(suggestion: PlotSuggestion): string {
  const lines = [
    suggestion.title,
    suggestion.proposed_change ? `Decision: ${suggestion.proposed_change}` : "",
    ...suggestion.open_questions.map((question) => `Question: ${question}`),
    suggestion.reason ? `Why it matters: ${suggestion.reason}` : "",
    ...plotSuggestionTargets(suggestion).map((target) => `${target.label}: ${target.value}`),
  ];
  return lines.filter(Boolean).join("\n");
}

export function plotSuggestionTargets(suggestion: PlotSuggestion): PlotSuggestionTarget[] {
  return [
    suggestion.target_card_id ? { label: "Card", value: suggestion.target_card_id } : null,
    suggestion.target_claim_id ? { label: "Marker", value: suggestion.target_claim_id } : null,
    suggestion.template_instance_id ? { label: "Template", value: suggestion.template_instance_id } : null,
    suggestion.plot_point_id ? { label: "Beat", value: suggestion.plot_point_id } : null,
  ].filter((target): target is PlotSuggestionTarget => Boolean(target));
}

export function plotSuggestionKindLabel(kind: PlotSuggestionKind): string {
  switch (kind) {
    case "card_revision":
      return "Card change";
    case "beat_revision":
      return "Story beat change";
    case "claim_change":
      return "Story marker change";
    case "new_card":
      return "New card";
    case "new_claim":
      return "New story marker";
    case "relationship_change":
      return "Relationship change";
    case "scene_promotion":
      return "Scene suggestion";
    case "question":
      return "Question";
    default:
      return "Suggestion";
  }
}

export function appendPlotSuggestionEvidence(existing: string | null | undefined, addition: string): string {
  return appendPlotSuggestionText(existing, addition);
}

export function appendPlotSuggestionText(existing: string | null | undefined, addition: string): string {
  const textToAdd = addition.trim();
  if (!textToAdd) return existing ?? "";

  const current = existing ?? "";
  const comparableAddition = normalizeComparableText(textToAdd);
  const existingItems = current.split(/\n{2,}/).map(normalizeComparableText);
  if (existingItems.includes(comparableAddition)) return current;
  if (!current.trim()) return textToAdd;
  return `${current.trimEnd()}\n\n${textToAdd}`;
}

export function canCreatePlotSuggestionBadge(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "new_claim" &&
    !suggestion.target_claim_id.trim() &&
    Boolean(suggestion.target_card_id.trim()) &&
    Boolean(suggestion.template_instance_id.trim()) &&
    Boolean(suggestion.plot_point_id.trim())
  );
}

export function canApplyPlotSuggestionBeatFields(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "beat_revision" &&
    Boolean(suggestion.template_instance_id.trim()) &&
    Boolean(suggestion.plot_point_id.trim()) &&
    Boolean(
      suggestion.story_specifics.trim() ||
        suggestion.author_intent.trim() ||
        suggestion.expected_role.trim() ||
        suggestion.open_questions.length > 0 ||
        suggestion.status,
    )
  );
}

export function canApplyPlotSuggestionCardSynopsis(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "card_revision" &&
    Boolean(suggestion.target_card_id.trim()) &&
    Boolean(suggestion.proposed_change.trim())
  );
}

export function canApplyPlotSuggestionClaimNote(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "claim_change" &&
    Boolean(suggestion.target_claim_id.trim()) &&
    Boolean(suggestion.proposed_change.trim())
  );
}

export function canApplyPlotSuggestionBeatQuestion(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "question" &&
    Boolean(suggestion.template_instance_id.trim()) &&
    Boolean(suggestion.plot_point_id.trim()) &&
    Boolean(suggestion.proposed_change.trim() || suggestion.open_questions.length > 0)
  );
}

export function canCreatePlotSuggestionCard(suggestion: PlotSuggestion): boolean {
  const hasTemplateInstance = Boolean(suggestion.template_instance_id.trim());
  const hasPlotPoint = Boolean(suggestion.plot_point_id.trim());
  return (
    suggestion.kind === "new_card" &&
    !suggestion.target_card_id.trim() &&
    Boolean(suggestion.title.trim()) &&
    Boolean(suggestion.proposed_change.trim()) &&
    hasTemplateInstance === hasPlotPoint
  );
}

export function canCopyPlotSuggestionQuestion(suggestion: PlotSuggestion): boolean {
  return (
    suggestion.kind === "question" &&
    Boolean(
      suggestion.title.trim() ||
        suggestion.reason.trim() ||
        suggestion.proposed_change.trim() ||
        suggestion.open_questions.length > 0,
    )
  );
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

function extractTags(text: string, tag: string): string[] {
  const pattern = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)<\\/${tag}>`, "gi");
  return matchAll(text, pattern).map((match) => normalizeText(match?.[1] ?? "")).filter(Boolean);
}

function normalizeKind(kind: string | undefined): PlotSuggestionKind {
  const normalized = (kind ?? "").trim();
  switch (normalized) {
    case "card_revision":
    case "beat_revision":
    case "claim_change":
    case "new_card":
    case "new_claim":
    case "relationship_change":
    case "scene_promotion":
    case "question":
      return normalized;
    default:
      return "unknown";
  }
}

function normalizeStatus(status: string): PlotSuggestionBeatStatus | "" {
  switch (status.trim()) {
    case "unplanned":
    case "planned":
    case "drafted":
    case "satisfied":
    case "intentionally_omitted":
      return status.trim() as PlotSuggestionBeatStatus;
    default:
      return "";
  }
}

function cleanTarget(value: string | undefined): string {
  const cleaned = normalizeText(value ?? "");
  return cleaned.includes("_if_known") ? "" : cleaned;
}

function normalizeText(value: string): string {
  return decodeXml(value).replace(/\s+/g, " ").trim();
}

function normalizeComparableText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
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
    suggestion.story_specifics,
    suggestion.author_intent,
    suggestion.expected_role,
    ...suggestion.open_questions,
    suggestion.status,
  ].join(" ").toLowerCase();
  if (!content.trim()) return false;
  return !PLACEHOLDER_FRAGMENTS.some((fragment) => content.includes(fragment));
}

function matchAll(text: string, pattern: RegExp): RegExpMatchArray[] {
  return Array.from(text.matchAll(pattern));
}
