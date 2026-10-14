// The editor's backlinks source (split out of NodeEditor, #2473). Backlinks =
// the open node's referrers (#194): membership from the in-memory reverse index,
// rows from `resolve_references`. A request token drops out-of-order resolves
// when the anchor or the index changes mid-flight. The field index + schema +
// loreEntries (#2075, ADR-0089 §6) give each row its own field/detail instead of
// collapsing to one any-field row per referrer.
import { backlinksFor } from "@/lib/views/backlinks";
import type { Backlink } from "@/lib/types";

type BacklinkOptions = Parameters<typeof backlinksFor>[2];

export class BacklinksSync {
  items: Backlink[] = $state([]);
  #lastAnchorId: string | null = null;
  #req = 0;

  // Re-source when the open node changes or either reverse index rebuilds (a
  // referrer was saved/deleted) — reading the index also closes the
  // open-during-initial-load race the old one-shot fetch had. Call from an
  // effect: the synchronous reads inside `options()` (only evaluated with an anchor) before the first await are its
  // tracked dependencies.
  sync(
    anchorId: string | null,
    referenceIndex: ReadonlyMap<string, ReadonlySet<string>>,
    options: () => BacklinkOptions,
  ): void {
    if (anchorId) {
      void this.#refresh(anchorId, referenceIndex, options());
    } else if (this.#lastAnchorId !== null) {
      this.#lastAnchorId = null;
      this.items = [];
    }
  }

  async #refresh(
    anchorId: string,
    referenceIndex: ReadonlyMap<string, ReadonlySet<string>>,
    options: BacklinkOptions,
  ): Promise<void> {
    this.#lastAnchorId = anchorId;
    const req = ++this.#req;
    try {
      const next = await backlinksFor(anchorId, referenceIndex, options);
      if (req === this.#req) this.items = next;
    } catch {
      if (req === this.#req) this.items = [];
    }
  }
}
