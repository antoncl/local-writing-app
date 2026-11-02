// Proofreading (ADR-0102 §2): the Harper engine. The ONLY module that imports
// `harper.js` — the package calls its API "early access, not yet stable", so it
// is pinned exactly in package.json and an upgrade touches this file alone.
//
// Loaded with a dynamic import the first time the lens is switched on, so
// startup and the first-draft path never fetch the 20 MB binary. The slim
// binary, a separate asset the app serves itself: the "full" flavour loads the
// slim one AND a second 20 MB binary on top, and the slim one alone does all
// the lens needs (lints by rule, words, rule config, ignores by hash — checked
// in the browser, ADR-0102 Amendment 1).
import {
  Dialect,
  SuggestionKind,
  WorkerLinter,
  type Lint,
  type LintConfig,
  type Linter,
  type StructuredLintSetting,
  type Suggestion,
} from "harper.js";
import { slimBinary } from "harper.js/slimBinary";
import type { Finding, FindingFix, ProofreadEngine, RuleGroup, RuleInfo } from "@/lib/proofread/findings";
import { ruleLabel } from "@/lib/proofread/ruleLabel";
import type { ProofreadingDialect } from "@/lib/types";

const ENGINE_ID = "harper";
// Harper's default is markdown, which would read the prose's own asterisks and
// underscores as markup; the editor hands it a block's plain text.
const LINT_OPTIONS = { language: "plaintext" } as const;

/** The parts of a lint the app reads — the shape `toFinding` converts. */
type LintLike = Pick<Lint, "span" | "lint_kind" | "message" | "suggestions">;

function fixLabel(kind: SuggestionKind, replacement: string): string {
  if (kind === SuggestionKind.Remove) return "Remove";
  if (kind === SuggestionKind.InsertAfter) return `Insert “${replacement}”`;
  return replacement;
}

function toFix(suggestion: Suggestion, from: number, to: number): FindingFix {
  const kind = suggestion.kind();
  const replacement = kind === SuggestionKind.Remove ? "" : suggestion.get_replacement_text();
  if (kind === SuggestionKind.InsertAfter) return { label: fixLabel(kind, replacement), from: to, to, insert: replacement };
  return { label: fixLabel(kind, replacement), from, to, insert: replacement };
}

/** One Harper lint as a finding in UTF-16 offsets into `text`.
 *
 *  harper.js 3.0.0 reports spans in UTF-16 code units — JS string indices —
 *  though the docs' Spans page says Unicode scalar values (that describes the
 *  Rust core). Measured in the browser on 2026-11-02: in "a 🙂 untill b" the
 *  span of "untill" is 5–11, which is its UTF-16 slice. An upgrade rechecks it
 *  (ADR-0102 Amendment 1). */
export function toFinding(ruleId: string, lint: LintLike): Finding {
  const { start: from, end: to } = lint.span();
  return {
    engine: ENGINE_ID,
    from,
    to,
    kind: lint.lint_kind(),
    ruleId,
    message: lint.message(),
    fixes: lint.suggestions().map((s) => toFix(s, from, to)),
  };
}

/** The lints `organizedLints` returns, keyed by rule, as findings. */
export function toFindings(byRule: Record<string, LintLike[]>): Finding[] {
  const findings: Finding[] = [];
  for (const [ruleId, lints] of Object.entries(byRule)) {
    for (const lint of lints) findings.push(toFinding(ruleId, lint));
  }
  return findings.sort((a, b) => a.from - b.from || a.to - b.to);
}

const DIALECTS: Record<ProofreadingDialect, Dialect> = {
  american: Dialect.American,
  british: Dialect.British,
  australian: Dialect.Australian,
  canadian: Dialect.Canadian,
  indian: Dialect.Indian,
};

/** Harper's full rule config: its defaults with the writer's switches on top.
 *  A switch for a rule this version lacks is skipped, not sent: rule names
 *  change between versions (ADR-0102 §5), and the file keeps the name. */
export function mergedRules(defaults: LintConfig, rules: Record<string, boolean>): LintConfig {
  const merged: LintConfig = { ...defaults };
  for (const [rule, enabled] of Object.entries(rules)) if (rule in defaults) merged[rule] = enabled;
  return merged;
}

type LinterLike = Pick<
  Linter,
  | "lint"
  | "organizedLints"
  | "clearWords"
  | "importWords"
  | "setLintConfig"
  | "setDialect"
  | "clearIgnoredLints"
  | "ignoreLintHash"
  | "contextHash"
  | "getStructuredLintConfig"
  | "getLintDescriptions"
>;

const OTHER_GROUP = "Other";

/** Every rule a structured setting holds, nested groups flattened in: a Bool is
 *  one rule, a OneOfMany contributes each of its names as its own. */
function settingRules(setting: StructuredLintSetting, info: (name: string, label: string) => RuleInfo): RuleInfo[] {
  if ("Bool" in setting) {
    const { name } = setting.Bool as { name: string };
    return [info(name, ruleLabel(name))];
  }
  if ("OneOfMany" in setting) {
    const { names, labels } = setting.OneOfMany;
    return names.map((name, i) => info(name, labels?.[i] || ruleLabel(name)));
  }
  if ("Group" in setting) return setting.Group.child.settings.flatMap((s) => settingRules(s, info));
  return [];
}

/** Harper's rules in Harper's groups; rules within a group by label. A rule
 *  outside any group goes into "Other", last. */
async function buildCatalog(linter: LinterLike, defaults: LintConfig): Promise<RuleGroup[]> {
  const [structured, descriptions] = await Promise.all([linter.getStructuredLintConfig(), linter.getLintDescriptions()]);
  const info = (name: string, label: string): RuleInfo => ({
    name,
    label,
    description: descriptions[name] ?? "",
    default: defaults[name] ?? false,
  });
  const byLabel = (a: RuleInfo, b: RuleInfo) => a.label.localeCompare(b.label);
  const groups: RuleGroup[] = [];
  const loose: RuleInfo[] = [];
  for (const setting of structured.settings) {
    if ("Group" in setting) {
      const { label, description } = setting.Group;
      groups.push({ label, description, rules: settingRules(setting, info).sort(byLabel) });
    } else loose.push(...settingRules(setting, info));
  }
  if (loose.length > 0) groups.push({ label: OTHER_GROUP, description: "", rules: loose.sort(byLabel) });
  return groups;
}

/** The engine over an already-constructed linter and its default rule config
 *  (tests pass fakes). */
export function harperEngineFor(linter: LinterLike, defaults: LintConfig = {}): ProofreadEngine {
  let catalog: Promise<RuleGroup[]> | null = null;
  return {
    id: ENGINE_ID,
    async lint(text) {
      if (!text.trim()) return [];
      // `organizedLints` rather than `lint`: only it says which rule produced a
      // lint, which "stop checking this rule" needs.
      const byRule = await linter.organizedLints(text, LINT_OPTIONS);
      return toFindings(byRule);
    },
    async setWords(words) {
      await linter.clearWords();
      if (words.length > 0) await linter.importWords(words);
    },
    async configure({ rules, dialect, ignored }) {
      await linter.setLintConfig(mergedRules(defaults, rules));
      await linter.setDialect(DIALECTS[dialect]);
      await linter.clearIgnoredLints();
      for (const hash of ignored) await linter.ignoreLintHash(BigInt(hash));
    },
    async hashesOf(text, finding) {
      // With overlap removal off: where two rules flag the same words, Harper
      // shows one and hides the other, and ignoring only the shown one would
      // uncover the hidden one (measured on 3.0.0: "untill" is flagged by
      // both SpellCheck and WrongNegative).
      const all = await linter.lint(text, { ...LINT_OPTIONS, dedup: false });
      const here = all.filter((lint) => {
        const span = lint.span();
        return span.start === finding.from && span.end === finding.to;
      });
      return Promise.all(here.map(async (lint) => String(await linter.contextHash(text, lint))));
    },
    catalog() {
      catalog ??= buildCatalog(linter, defaults).catch((err: unknown) => {
        catalog = null;
        throw err;
      });
      return catalog;
    },
  };
}

/** Start Harper in its worker. */
export async function createHarperEngine(): Promise<ProofreadEngine> {
  const linter = new WorkerLinter({ binary: slimBinary, dialect: Dialect.American });
  await linter.setup();
  // harper #3490: a WorkerLinter's default-on rules stay inactive until the
  // default config is read once after setup; setting it arms them as well.
  const defaults = await linter.getDefaultLintConfig();
  await linter.setLintConfig(defaults);
  return harperEngineFor(linter, defaults);
}
