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

/**
 * Rendered HTML for one view state.
 *
 * Inline runs accumulate into a markdown buffer so that a paragraph is rendered
 * *once*, with its wrappers in place — rendering run by run would produce a
 * paragraph per run. The buffer is flushed around every stacked run, which is
 * what keeps a block-spanning change out of the inline stream.
 */
export async function renderDiffRuns(runs: DiffRun[], view: DiffView): Promise<string> {
  const parts: string[] = [];
  let buffer = "";

  const flush = async () => {
    // Whitespace-only buffers are the block separators between two stacked
    // runs. Rendering one emits an empty `<p>`, which the reader sees as a gap
    // that means nothing — the stacked containers already carry the spacing.
    if (buffer.trim()) parts.push(await sceneMarkdownToHtml(buffer));
    buffer = "";
  };

  for (const run of runs) {
    if (!shows(view, run.kind)) continue;
    if (run.stacked && run.kind !== "equal") {
      await flush();
      const html = await sceneMarkdownToHtml(run.text);
      parts.push(`<div class="blk blk-${run.kind}">${html}</div>`);
      continue;
    }
    buffer += run.kind === "equal" ? run.text : `<span class="r-${run.kind}">${run.text}</span>`;
  }
  await flush();
  return parts.join("");
}
