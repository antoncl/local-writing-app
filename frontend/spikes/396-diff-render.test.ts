/**
 * Spike #396 — does a word-level markdown diff survive rendering?
 *
 * Throwaway harness for ADR-0044 §F/§G. `scripts/spike_396_runs.py` writes
 * `396-runs.json`: provenance-tagged runs over markdown source, produced by
 * the same `difflib.SequenceMatcher` the runs endpoint would use. This half
 * does what the frontend would do with them — wrap each run so it can be
 * tinted, then render the whole thing through the app's real
 * `sceneMarkdownToHtml`.
 *
 * The oracle: rendering the `now` view and then stripping the wrappers must
 * equal the plain render of the current scene body. Same for `was`. Anything
 * else is damage the author would see.
 *
 * Wrappers are `<x-now>` / `<x-was>` rather than `<span class="r-now">` only
 * so they strip unambiguously; a control case checks a real span behaves the
 * same.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { sceneMarkdownToHtml } from "../src/lib/utils/markdown";

interface Run {
  kind: "equal" | "now" | "was";
  text: string;
  /** the run spans block boundaries, so no inline element can wrap it */
  stacked?: boolean;
}
interface Case {
  name: string;
  why: string;
  was: string;
  now: string;
  runs: Run[];
  /** the same diff with the two candidate constraints applied — see the script */
  snapped: Run[];
}

const CASES: Case[] = JSON.parse(
  readFileSync(fileURLToPath(new URL("./396-runs.json", import.meta.url)), "utf8"),
);

type View = "now" | "was" | "both";

/** §F: equal runs are bare; a run belonging to one side is wrapped so it can
 *  be tinted. `both` keeps them adjacent, in was-then-now source order. */
function assemble(runs: Run[], view: View, wrap = (k: "now" | "was", t: string) => `<x-${k}>${t}</x-${k}>`) {
  const out: string[] = [];
  for (const run of runs) {
    if (run.kind === "equal") out.push(run.text);
    else if (view === "both" || view === run.kind) out.push(wrap(run.kind, run.text));
  }
  return out.join("");
}

/**
 * Constraint 3: a `stacked` run is rendered on its own and the wrapper goes
 * *around the rendered HTML*, as a block. Inline runs still have their wrapper
 * injected into the markdown source, which is what §G describes.
 */
async function renderView(runs: Run[], view: View) {
  const parts: string[] = [];
  let buffer = "";
  const flush = async () => {
    if (buffer) parts.push(await sceneMarkdownToHtml(buffer));
    buffer = "";
  };
  for (const run of runs) {
    if (run.stacked && run.kind !== "equal") {
      if (view === "both" || view === run.kind) {
        await flush();
        parts.push(`<x-blk-${run.kind}>${await sceneMarkdownToHtml(run.text)}</x-blk-${run.kind}>`);
      }
      continue;
    }
    if (run.kind === "equal") buffer += run.text;
    else if (view === "both" || view === run.kind) buffer += `<x-${run.kind}>${run.text}</x-${run.kind}>`;
  }
  await flush();
  return parts.join("");
}

function strip(html: string) {
  return html.replace(/<\/?x-(now|was)>/g, "").replace(/<\/?x-blk-(now|was)>/g, "");
}

const VOID = new Set(["br", "hr", "img", "input", "meta", "link", "col", "wbr"]);
const TAG = /<!--[\s\S]*?-->|<\/?([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(\/?)>/g;

/**
 * Improper nesting — the failure the ADR predicts and the strip-and-compare
 * oracle cannot see. `<x-was><strong>a</x-was><x-was>b</strong></x-was>`
 * strips to exactly the baseline while being HTML no browser will build: the
 * fixup reparents the tint, so the wrong words end up coloured.
 */
function nestingErrors(html: string): string[] {
  const stack: string[] = [];
  const errs: string[] = [];
  for (const m of html.matchAll(TAG)) {
    const raw = m[0];
    if (raw.startsWith("<!--")) continue;
    const name = m[1].toLowerCase();
    if (VOID.has(name) || m[2] === "/") continue;
    if (raw.startsWith("</")) {
      const top = stack.pop();
      if (top !== name) errs.push(`</${name}> closes inside <${top ?? "nothing"}>`);
    } else stack.push(name);
  }
  for (const left of stack.reverse()) errs.push(`<${left}> never closed`);
  return errs;
}

/** Markdown syntax that reached the reader as literal text. */
function leaks(html: string): string[] {
  const text = html.replace(/<!--[\s\S]*?-->/g, "").replace(/<[^>]+>/g, "");
  return ["](", "**", "~~", "|"].filter((d) => text.includes(d)).map((d) => `literal ${d}`);
}

const report: string[] = [];

describe("spike 396: word-level markdown diff through the real renderer", () => {
  for (const c of CASES) {
    it(`${c.name} — ${c.why}`, async () => {
      const baselines = {
        now: await sceneMarkdownToHtml(c.now),
        was: await sceneMarkdownToHtml(c.was),
      };
      const baselineLeaks = new Set([...leaks(baselines.now), ...leaks(baselines.was)]);
      const lines = [`### ${c.name}`, c.why];

      for (const [variant, runs] of [
        ["as designed (word-level over the whole body)", c.runs],
        ["with the candidate constraints", c.snapped],
      ] as const) {
        const findings: string[] = [];
        let both = "";
        for (const view of ["now", "was", "both"] as const) {
          const html = await renderView(runs, view);
          if (view === "both") both = html;
          const problems: string[] = [];
          // 1. does it reassemble to the same document? (no baseline for `both`)
          if (view !== "both" && strip(html) !== baselines[view]) {
            problems.push(
              `structure differs from a plain render\n      baseline: ${baselines[view].trim()}`,
            );
          }
          // 2. is it HTML a browser will build as written?
          for (const err of nestingErrors(html)) problems.push(`improper nesting: ${err}`);
          // 3. did markdown syntax leak into the prose?
          for (const l of leaks(html)) {
            if (!baselineLeaks.has(l)) problems.push(`leaked to reader: ${l}`);
          }
          if (problems.length) {
            findings.push(`    view=${view}: ${problems.join("\n      ")}\n        got:  ${html.trim()}`);
          }
        }
        lines.push(
          `  ${variant}: ` +
            (findings.length ? `DAMAGED\n${findings.join("\n")}` : "clean in all three views"),
          `    both: ${both.trim()}`,
        );
      }
      report.push(lines.join("\n") + "\n");
      // The spike reports; it does not gate. Assertions would stop at the
      // first case and the whole point is the full picture.
      expect(true).toBe(true);
    });
  }

  // `<x-now>` is a stand-in for the real `<span class="r-now">`, so check the
  // choice is not what produced the results. Cases carrying an HTML-comment
  // marker are excluded: the marker preprocessing emits spans of its own, and
  // this check's crude `</span>` strip cannot tell them from the wrappers.
  it("control: a real <span class> wrapper behaves the same as <x-now>", async () => {
    const spanWrap = (k: "now" | "was", t: string) => `<span class="r-${k}">${t}</span>`;
    const lines: string[] = [];
    for (const c of CASES.filter((x) => !x.was.includes("<!--"))) {
      // Nesting is the oracle here: it is the failure the wrapper element
      // could plausibly change, and unlike strip-and-compare it sees it.
      const custom = nestingErrors(await sceneMarkdownToHtml(assemble(c.runs, "both"))).length;
      const span = nestingErrors(
        await sceneMarkdownToHtml(assemble(c.runs, "both", spanWrap)),
      ).length;
      lines.push(
        `${c.name}: ${custom} nesting errors with <x-*>, ${span} with <span class>` +
          (custom === span ? "" : "  <-- the wrapper choice mattered"),
      );
    }
    report.push(
      "### control: wrapper element choice (marker cases excluded — see the comment)\n" +
        lines.join("\n") +
        "\n",
    );
    expect(lines.length).toBeGreaterThan(0);
  });

  it("writes the report", () => {
    writeFileSync(
      fileURLToPath(new URL("./396-report.txt", import.meta.url)),
      report.join("\n"),
      "utf8",
    );
    expect(report.length).toBe(CASES.length + 1);
  });
});
