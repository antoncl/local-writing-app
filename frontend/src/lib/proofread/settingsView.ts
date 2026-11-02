// Proofreading (ADR-0102 §4): the settings tab's pure view logic — what a level
// inherits and who decided it, which rules any level changes, and the rule
// search. No Svelte, so it is unit-tested alone.
import type { RuleGroup } from "@/lib/proofread/findings";
import type { ProofreadingDialect, ProofreadingSetup } from "@/lib/types";

export const HARPER_DEFAULT = "Harper's default";
const DEFAULT_DIALECT: ProofreadingDialect = "american";

/** The layers that decide before `layerId` does: those ahead of it, outermost first. */
function layersBefore(setup: ProofreadingSetup, layerId: string) {
  const at = setup.layers.findIndex((l) => l.id === layerId);
  return at < 0 ? setup.layers : setup.layers.slice(0, at);
}

/** What `layerId` gets for `rule` when it sets nothing itself: Harper's default,
 *  overlaid by each layer before it. `from` names who decided. */
export function inheritedRule(
  setup: ProofreadingSetup,
  layerId: string,
  rule: string,
  harperDefault: boolean,
): { value: boolean; from: string } {
  let value = harperDefault;
  let from = HARPER_DEFAULT;
  for (const layer of layersBefore(setup, layerId)) {
    if (rule in layer.rules) {
      value = layer.rules[rule];
      from = layer.label;
    }
  }
  return { value, from };
}

/** The dialect `layerId` gets when it sets none itself. */
export function inheritedDialect(setup: ProofreadingSetup, layerId: string): { dialect: ProofreadingDialect; from: string } {
  let dialect = DEFAULT_DIALECT;
  let from = HARPER_DEFAULT;
  for (const layer of layersBefore(setup, layerId)) {
    if (layer.dialect) {
      dialect = layer.dialect;
      from = layer.label;
    }
  }
  return { dialect, from };
}

/** Every rule any layer sets. */
export function changedRuleNames(setup: ProofreadingSetup): Set<string> {
  return new Set(setup.layers.flatMap((layer) => Object.keys(layer.rules)));
}

/** The groups' rules that match `query` (label, name or description, any case)
 *  and, with `changedOnly`, are in `changed`. Groups left empty are dropped. */
export function filterGroups(groups: RuleGroup[], query: string, changedOnly: boolean, changed: Set<string>): RuleGroup[] {
  const needle = query.trim().toLowerCase();
  if (!needle && !changedOnly) return groups;
  const out: RuleGroup[] = [];
  for (const group of groups) {
    const rules = group.rules.filter(
      (rule) =>
        (!changedOnly || changed.has(rule.name)) &&
        (!needle ||
          rule.label.toLowerCase().includes(needle) ||
          rule.name.toLowerCase().includes(needle) ||
          rule.description.toLowerCase().includes(needle)),
    );
    if (rules.length > 0) out.push({ ...group, rules });
  }
  return out;
}
