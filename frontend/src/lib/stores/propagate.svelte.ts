// The Propagate confirm surface's domain state (ADR-0090 §7, Amendment 2 §3).
// A module singleton — like `paneViews` / `editorPanes` — because the confirm
// surface is a single on-demand editor tab, never two at once (opening it
// again just re-targets the same tab at a new source).
//
// Read-only until `confirm()`: the candidate set is fetched and re-fetched
// (on a "since" change) but nothing is written until the writer confirms —
// the invariant ADR-0090 §5 states outright. Errors go to `error` and are
// never thrown, the same pattern `plotBoard.ts` uses for its own fetches —
// this is a background/async surface, not a `run()`-wrapped action.

import { SvelteSet } from "svelte/reactivity";
import { api } from "@/lib/api";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { refreshTodos } from "@/lib/stores/todos";
import type { ChangeCandidateSet, ChangeCandidateTier, Snapshot } from "@/lib/types";

export class PropagateController {
  sourceId = $state<string | null>(null);
  sourceTitle = $state("");
  candidates = $state<ChangeCandidateSet | null>(null);
  // The "since" selector's options (newest first is the caller's job — the
  // pane sorts before rendering; stored here in whatever order the API gave).
  snapshots = $state<Snapshot[]>([]);
  // The explicit baseline request: `undefined` = let the backend default,
  // `""` = the whole entry, any other value = that snapshot id. Distinct from
  // `candidates.baseline_snapshot_id`, which is what was actually resolved.
  baseline = $state<string | undefined>(undefined);
  kept = new SvelteSet<string>();
  folded = new SvelteSet<ChangeCandidateTier>(["mention"]);
  loading = $state(false);
  error = $state<string | null>(null);

  // Every `declared` and `marker_untouched` candidate starts kept; every
  // `mention` starts unkept (ADR-0090 §7 / Amendment 1) — re-applied after
  // every load, including a "since" change.
  #applyDefaultKept(): void {
    this.kept.clear();
    for (const item of this.candidates?.items ?? []) {
      if (item.tier !== "mention") this.kept.add(item.id);
    }
  }

  async open(sourceId: string, sourceTitle: string): Promise<void> {
    this.sourceId = sourceId;
    this.sourceTitle = sourceTitle;
    this.candidates = null;
    this.snapshots = [];
    this.kept.clear();
    this.folded.clear();
    this.folded.add("mention");
    this.baseline = undefined;
    this.error = null;
    this.loading = true;
    // Bring the tab into view AT ONCE — it shows its own loading state while
    // the candidate set and the snapshot list resolve (mirrors the plot
    // board's fetch-then-show, #1920).
    workspaceLayout.ensureVisible("propagate");
    try {
      const [candidates, snapshotList] = await Promise.all([
        api.listChangeCandidates(sourceId),
        api.listNodeSnapshots(sourceId),
      ]);
      this.candidates = candidates;
      this.snapshots = snapshotList.snapshots;
      this.#applyDefaultKept();
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      this.loading = false;
    }
  }

  toggle(id: string): void {
    if (this.kept.has(id)) this.kept.delete(id);
    else this.kept.add(id);
  }

  // The group header's all/none control (the taxonomy's own multi-select
  // idiom — a tri-state pickable header row, not a bespoke button).
  setGroup(tier: ChangeCandidateTier, on: boolean): void {
    for (const item of this.candidates?.items ?? []) {
      if (item.tier !== tier) continue;
      if (on) this.kept.add(item.id);
      else this.kept.delete(item.id);
    }
  }

  toggleFold(tier: ChangeCandidateTier): void {
    if (this.folded.has(tier)) this.folded.delete(tier);
    else this.folded.add(tier);
  }

  // Re-fetches the candidate set against the newly chosen baseline; kept
  // defaults are re-applied, same as a fresh open (ADR-0090 §7's "since"
  // re-renders the right pane AND the list).
  async setBaseline(value: string): Promise<void> {
    if (!this.sourceId) return;
    this.baseline = value;
    this.loading = true;
    this.error = null;
    try {
      this.candidates = await api.listChangeCandidates(this.sourceId, value);
      this.#applyDefaultKept();
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      this.loading = false;
    }
  }

  // The one write (ADR-0090 §1/§5): one review item per kept candidate, and a
  // new baseline snapshot of the source. Refuses (silently, via the guard) a
  // confirm with nothing kept — the pane's primary button is disabled at 0.
  async confirm(): Promise<void> {
    if (!this.sourceId || !this.candidates || this.kept.size === 0) return;
    this.loading = true;
    this.error = null;
    try {
      await api.propagateChange(this.sourceId, {
        baseline_snapshot_id: this.candidates.baseline_snapshot_id,
        kept: [...this.kept],
      });
      await refreshTodos();
      this.close();
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
      this.loading = false;
    }
  }

  // Safe to call twice (App's `onClose` and a successful `confirm()` both
  // reach here) — `removePanel` on an already-gone panel is a no-op.
  close(): void {
    workspaceLayout.removePanel("propagate");
    this.sourceId = null;
    this.sourceTitle = "";
    this.candidates = null;
    this.snapshots = [];
    this.kept.clear();
    this.folded.clear();
    this.baseline = undefined;
    this.error = null;
    this.loading = false;
  }
}

export const propagate = new PropagateController();

export function openPropagatePane(sourceId: string, sourceTitle: string): void {
  void propagate.open(sourceId, sourceTitle);
}
