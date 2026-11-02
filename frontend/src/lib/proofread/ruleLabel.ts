// Proofreading (ADR-0102 §4): a Harper rule name as a writer reads it.

/** "OxfordComma" -> "Oxford comma". */
export function ruleLabel(rule: string): string {
  const [first = "", ...rest] = rule.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(" ");
  return [first, ...rest.map((w) => w.toLowerCase())].join(" ");
}
