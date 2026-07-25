// Rendering provenance-tagged runs into the read-only overlay (ADR-0044 §F/§G).
//
// The backend returns runs that are **complete markdown fragments**, each either
// inline-within-one-block or block-spanning, never both (Amendment 1). That
// contract is what makes wrapping possible at all: an inline run's wrapper is
// injected into the markdown *source* and survives rendering, while a
// block-spanning run is rendered on its own and wrapped around the *rendered
// HTML* — because no inline element can wrap two paragraphs.
//
// **The colour says which version the text belongs to.** Warm (`r-now`) = in the
// scene now; cool (`r-was`) = in the snapshot. An addition is warm, a deletion is
// cool, a modification is the two adjacent. Three cases that could drift apart
// become one that cannot.
//
// One payload serves all three view states: Both, Now and Snapshot are filters
// over the same runs, not three requests. And the tint stays in *every* compare
// state — with nothing marked, a flip changes words somewhere and the eye has no
// anchor. Only Live is unmarked, because there is nothing to compare it against.
import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
import type { DiffRun, DiffView } from "@/lib/types";

/** Which runs a view state shows. `equal` is in every one. */
function shows(view: DiffView, kind: DiffRun["kind"]): boolean {
  return kind === "equal" || view === "both" || view === kind;
}

/** One changed region: a maximal run of consecutive non-`equal` runs — a
 *  modification's cool+warm pair, or a lone insertion (warm only) or deletion
 *  (cool only). `id` is its ordinal in document order, stable for one runs
 *  array: the click carries it back to {@link adoptRegion}. */
export type DiffRegion = {
  id: number;
  /** The snapshot side's text, concatenated. Empty for a pure insertion. */
  wasText: string;
  /** The scene-now side's text, concatenated. Empty for a pure deletion. */
  nowText: string;
};

/**
 * Group the flat runs into changed regions, and report each run's region.
 *
 * The renderer tags spans with the region id and {@link adoptRegion} resolves
 * against it, so both must agree — one grouping function is that agreement. It
 * is deliberately not memoised: it runs over the same `runs` array both call,
 * within one render cycle, so the ids line up by construction.
 */
export function groupRuns(runs: DiffRun[]): {
  regionIdByRun: (number | null)[];
  regions: DiffRegion[];
} {
  const regionIdByRun: (number | null)[] = [];
  const regions: DiffRegion[] = [];
  let current: DiffRegion | null = null;
  for (const run of runs) {
    if (run.kind === "equal") {
      current = null;
      regionIdByRun.push(null);
      continue;
    }
    if (!current) {
      current = { id: regions.length, wasText: "", nowText: "" };
      regions.push(current);
    }
    if (run.kind === "was") current.wasText += run.text;
    else current.nowText += run.text;
    regionIdByRun.push(current.id);
  }
  return { regionIdByRun, regions };
}

/** The action a click on a run performs, in the author's words (ADR-0044
 *  Amendment 4). A cool run restores the snapshot's wording; a warm run in a
 *  modification keeps the current wording; a warm *lone insertion* has no
 *  snapshot side to choose against, so the meaningful move is to remove it. */
function titleFor(kind: DiffRun["kind"], region: DiffRegion): string {
  if (kind === "was") return "Restore this";
  return region.wasText ? "Keep this" : "Remove this";
}

/**
 * Rendered HTML for one view state.
 *
 * Inline runs accumulate into a markdown buffer so that a paragraph is rendered
 * *once*, with its wrappers in place — rendering run by run would produce a
 * paragraph per run. The buffer is flushed around every stacked run, which is
 * what keeps a block-spanning change out of the inline stream.
 *
 * Every changed run carries a `data-region` and a `title`: the overlay makes it
 * clickable so the author can adopt one region while parked (Amendment 4). The
 * title is the affordance — no glyph is added, so §J holds as written.
 */
export async function renderDiffRuns(runs: DiffRun[], view: DiffView): Promise<string> {
  const parts: string[] = [];
  let buffer = "";
  const { regionIdByRun, regions } = groupRuns(runs);

  const flush = async () => {
    // Whitespace-only buffers are the block separators between two stacked
    // runs. Rendering one emits an empty `<p>`, which the reader sees as a gap
    // that means nothing — the stacked containers already carry the spacing.
    if (buffer.trim()) parts.push(await sceneMarkdownToHtml(buffer));
    buffer = "";
  };

  for (let i = 0; i < runs.length; i++) {
    const run = runs[i];
    if (!shows(view, run.kind)) continue;
    if (run.kind === "equal") {
      buffer += run.text;
      continue;
    }
    const id = regionIdByRun[i];
    const attrs = `data-region="${id}" title="${titleFor(run.kind, regions[id as number])}"`;
    if (run.stacked) {
      // A stacked run carrying only a block separator would render as an empty
      // tinted box — a mark with nothing under it, which reads as a change the
      // author cannot find.
      if (!run.text.trim()) continue;
      await flush();
      const html = await sceneMarkdownToHtml(run.text);
      parts.push(`<div class="blk blk-${run.kind}" ${attrs}>${html}</div>`);
      continue;
    }
    buffer += `<span class="r-${run.kind}" ${attrs}>${run.text}</span>`;
  }
  await flush();
  return parts.join("");
}

/**
 * Adopt one region while parked — re-projecting the runs locally, never
 * re-diffing (ADR-0044 Amendment 4). `clicked` is the side the author clicked.
 *
 * The runs already carry both versions (§G, Amendment 1), so this is a pure
 * projection: collapse the region to a single `equal` run of the surviving
 * text, and read the new scene body off the result exactly as the backend
 * reassembles `now` — everything not on the snapshot-only side. `body` is
 * non-null only when the scene actually changes; keeping the current wording is
 * a no-op on the document and merely settles the region in the overlay.
 *
 * Clicking the snapshot side always restores it. Clicking the scene side keeps
 * it — unless the region is a lone insertion (no snapshot side to weigh it
 * against), where the meaningful move is to drop the addition.
 */
export function adoptRegion(
  runs: DiffRun[],
  regionId: number,
  clicked: "now" | "was",
): { runs: DiffRun[]; body: string | null } {
  const { regionIdByRun, regions } = groupRuns(runs);
  const region = regions[regionId];
  if (!region) return { runs, body: null };

  const keep: "now" | "was" = clicked === "was" ? "was" : region.wasText ? "now" : "was";
  const chosen = keep === "was" ? region.wasText : region.nowText;

  const next: DiffRun[] = [];
  let collapsed = false;
  for (let i = 0; i < runs.length; i++) {
    if (regionIdByRun[i] === regionId) {
      // The whole region becomes one plain run of the surviving text — or
      // nothing, when that side is empty (an insertion dropped, a deletion left
      // deleted). It reads as prose again, no tint, and stays adoptable-free.
      if (!collapsed && chosen) next.push({ kind: "equal", text: chosen });
      collapsed = true;
      continue;
    }
    next.push(runs[i]);
  }

  const body =
    keep === "was" ? next.filter((run) => run.kind !== "was").map((run) => run.text).join("") : null;
  return { runs: next, body };
}
