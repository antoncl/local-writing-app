// Parity-check the TS port against the Python runs, then time it per bucket.
//   node bench.ts <corpus.json>
import { readFileSync } from "node:fs";
import { diffRuns, type DiffRun } from "./snapshotDiff.ts";

interface Case { name: string; bucket: string; was: string; now: string; runs: DiffRun[]; }
interface Corpus { cases: Case[]; py: Record<string, { cases: number; per_call_ms: number }>; }

const corpusPath = process.argv[2];
const corpus: Corpus = JSON.parse(readFileSync(corpusPath, "utf-8"));

// ---- parity ---------------------------------------------------------------
function sameRuns(a: DiffRun[], b: DiffRun[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].kind !== b[i].kind || a[i].text !== b[i].text || a[i].stacked !== b[i].stacked) return false;
  }
  return true;
}

let mismatches = 0;
const examples: string[] = [];
for (const c of corpus.cases) {
  const got = diffRuns(c.was, c.now);
  if (!sameRuns(got, c.runs)) {
    mismatches++;
    if (examples.length < 5) {
      const g = got.map((r) => `${r.kind}${r.stacked ? "*" : ""}:${JSON.stringify(r.text.slice(0, 40))}`);
      const e = c.runs.map((r) => `${r.kind}${r.stacked ? "*" : ""}:${JSON.stringify(r.text.slice(0, 40))}`);
      examples.push(`  ${c.name} [${c.bucket}] got=${got.length} exp=${c.runs.length}\n    TS : ${g.join(" | ")}\n    PY : ${e.join(" | ")}`);
    }
  }
}

console.log(`\nPARITY: ${corpus.cases.length - mismatches}/${corpus.cases.length} cases match Python exactly` +
  (mismatches ? `  —  ${mismatches} MISMATCH` : "  ✓"));
if (examples.length) console.log(examples.join("\n"));
if (mismatches) { console.log("\nAborting timing: port is not faithful yet.\n"); process.exit(1); }

// ---- timing ---------------------------------------------------------------
function timeBucket(cases: Case[], minTime = 1.5, minIters = 3): { calls: number; perCallMs: number } {
  for (const c of cases) diffRuns(c.was, c.now); // warmup / JIT
  let iters = 0;
  const t0 = process.hrtime.bigint();
  for (;;) {
    for (const c of cases) diffRuns(c.was, c.now);
    iters++;
    const elapsedMs = Number(process.hrtime.bigint() - t0) / 1e6;
    if (elapsedMs >= minTime * 1000 && iters >= minIters) {
      const calls = iters * cases.length;
      return { calls, perCallMs: elapsedMs / calls };
    }
  }
}

const buckets = new Map<string, Case[]>();
for (const c of corpus.cases) {
  const arr = buckets.get(c.bucket);
  if (arr) arr.push(c); else buckets.set(c.bucket, [c]);
}

const order = ["fuzz", "scene-500", "scene-1500", "scene-4000", "worst-para"];
const names = [...buckets.keys()].sort((a, b) => (order.indexOf(a) + 100) - (order.indexOf(b) + 100) || a.localeCompare(b));

console.log("\n" + "bucket".padEnd(13) + "n".padStart(4) + "avg-words".padStart(11) +
  "py ms/call".padStart(14) + "ts ms/call".padStart(14) + "TS speedup".padStart(13));
console.log("-".repeat(69));
for (const name of names) {
  const cases = buckets.get(name)!;
  const avgWords = cases.reduce((s, c) => s + c.was.split(/\s+/).filter(Boolean).length, 0) / cases.length;
  const ts = timeBucket(cases);
  const py = corpus.py[name]?.per_call_ms ?? NaN;
  const speedup = py / ts.perCallMs; // >1 means TS is faster than CPython
  console.log(
    name.padEnd(13) + String(cases.length).padStart(4) + avgWords.toFixed(0).padStart(11) +
    py.toFixed(4).padStart(14) + ts.perCallMs.toFixed(4).padStart(14) +
    `${speedup.toFixed(2)}x`.padStart(13)
  );
}
console.log("\n(TS speedup > 1 means the TypeScript port is FASTER than CPython on that bucket.)\n");
