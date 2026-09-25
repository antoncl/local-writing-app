// Editor-side operations on `mutation` prose nodes (the ⤳ anchor pills,
// ADR-0095 §1). A pill is now a pure ANCHOR — attrs `{ setId, anchorId }`,
// nothing else — that names a mutation-SET node kept elsewhere; its label
// renders from the mutation-sets STORE via a NodeView (proseMarks.ts), not
// from these attrs, so editing the set relabels every pill with no document
// change. This module keeps the doc-mechanical pieces: minting ids,
// finding/removing a pill, and reconciling paste/cut/copy/drag (ADR-0095
// §7). The heavier per-pill AUTHORING (create/edit-through-the-pill, ADR-0095
// §6) lives behind the `/mutate` dialogs (MutationAuthoringForm et al) —
// those are rebuilt in C2; `applyMutationUnitDraft` below is a deliberate
// no-op until then (see its own comment).
import type { Editor } from "@tiptap/core";
import type { Transaction } from "@tiptap/pm/state";
import type { CopyMutationSetResult, MutationMarkerRecord } from "@/lib/types";

export function createMutationId(): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
  return `mut_${randomId.slice(0, 12)}`;
}

export function findMutationNodePos(editor: Editor, anchorId: string): number | null {
  let hit: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (hit !== null) return false;
    if (node.type.name === "mutation" && node.attrs.anchorId === anchorId) hit = pos;
    return hit === null;
  });
  return hit;
}

export function removeMutationNode(editor: Editor, anchorId: string): void {
  const pos = findMutationNodePos(editor, anchorId);
  if (pos === null) return;
  const node = editor.state.doc.nodeAt(pos);
  if (node) editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
}

/** Insert a fresh anchor pill for `setId` at the cursor (ADR-0095 §6) — mints
 *  its own client anchor id and returns it. C2 wires this from the apply
 *  picker / `/mutate` create flow. */
export function insertAnchor(editor: Editor, setId: string): string {
  const anchorId = createMutationId();
  editor.chain().focus().insertContent({ type: "mutation", attrs: { setId, anchorId } }).run();
  return anchorId;
}

/** Insert a close pill ending `ref` (an anchor id), optionally scoped to one
 *  `row` within its set (ADR-0095 §1: "a row close names its anchor too"). */
export function insertMutationClose(editor: Editor, ref: string, row = ""): void {
  editor
    .chain()
    .focus()
    .insertContent({ type: "mutationClose", attrs: { ref, row, closeId: createMutationId() } })
    .run();
}

/** True when a transaction inserts any `mutation`/`mutationClose` node — the
 *  only way a pasted/dropped/redone pill enters the doc. Pills are atomic
 *  and dialog/paste-only: plain typing produces text steps and never trips
 *  this, so the per-keystroke path can skip the reconciliation walk below. */
export function transactionInsertsMutation(transaction: Transaction): boolean {
  return transaction.steps.some((step) => {
    const slice = (step as { slice?: { content: { descendants: (f: (node: { type: { name: string } }) => boolean | void) => void } } }).slice;
    if (!slice) return false;
    let found = false;
    slice.content.descendants((node) => {
      if (node.type.name === "mutation" || node.type.name === "mutationClose") {
        found = true;
        return false;
      }
      return !found;
    });
    return found;
  });
}

// ---------- Paste / cut / copy (ADR-0095 §7) ----------

type ClipboardKind = "cut" | "copy";
interface ClipboardLedgerEntry {
  kind: ClipboardKind;
  anchorIds: Set<string>;
  consumed: boolean;
}

// Module-level: the app's own cut/copy just put these anchor ids on the
// clipboard (ADR-0095 §7). Read back on the very next paste; a `copy` entry
// always means "copy" (never consumed to "kept" status), a `cut` entry is
// consumed on its first matching paste — every later paste of the same
// clipboard payload is then a copy, same as content from outside the app.
let clipboardLedger: ClipboardLedgerEntry | null = null;

export function recordMutationClipboard(kind: ClipboardKind, anchorIds: string[]): void {
  clipboardLedger = anchorIds.length > 0 ? { kind, anchorIds: new Set(anchorIds), consumed: false } : null;
}

/** Test-only: reset the module-level ledger between cases. */
export function resetMutationClipboardForTest(): void {
  clipboardLedger = null;
}

export interface MutationPasteDeps {
  /** Manuscript scene bodies are the only place an anchor may live (ADR-0095
   *  §1) — anything else drops a newly-arrived anchor/close on paste. */
  isManuscript: () => boolean;
  /** Anchor ids the PROJECT already knows about outside this doc (the loaded
   *  roster's `anchors`, ADR-0095 §7's "already exists in the project"
   *  test) — a duplicate found only within this doc is caught separately. */
  knownProjectAnchorIds: () => ReadonlySet<string>;
  copySet: (setId: string) => Promise<CopyMutationSetResult>;
  /** Surfaced through the app's usual error/notice mechanism — a failed copy,
   *  or a copy that left rows out. */
  onNotice?: (message: string) => void;
}

function collectMutationIds(editor: Editor): Set<string> {
  const ids = new Set<string>();
  editor.state.doc.descendants((node) => {
    if (node.type.name === "mutation") {
      const id = String(node.attrs.anchorId ?? "");
      if (id) ids.add(id);
    } else if (node.type.name === "mutationClose") {
      const id = String(node.attrs.closeId ?? "");
      if (id) ids.add(id);
    }
    return true;
  });
  return ids;
}

/** Reconciles anchor/close pills after any transaction that might have just
 *  pasted, dropped or redone one (ADR-0095 §7) — one instance per open prose
 *  body, seeded from each freshly loaded document so its own on-disk content
 *  is never mistaken for a paste.
 *
 *  A plain in-editor DRAG needs no special case here: ProseMirror moves a
 *  dragged range as delete+insert of the SAME node (no duplicate ever
 *  appears), so the id stays "already known" throughout and is left alone —
 *  exactly the "a move keeps its anchor" rule, for free. */
export class MutationPasteReconciler {
  #known = new Set<string>();

  /** Re-baseline against the doc as it stands right now (call after loading
   *  a scene) — everything already on disk counts as pre-existing. */
  seed(editor: Editor): void {
    this.#known = collectMutationIds(editor);
  }

  /** Drop ids from the baseline right when they're cut (ADR-0095 §7) — a cut
   *  deletes with no insert, so `reconcile` never runs to notice on its own,
   *  and without this the SAME pane pasting them straight back would see
   *  them as "already known" and skip the cut-ledger check entirely. */
  forget(ids: readonly string[]): void {
    for (const id of ids) this.#known.delete(id);
  }

  /** Synchronous half: manuscript gating, cut-keep, copy id/setId reset,
   *  in-doc duplicates, and close repointing — then kicks off `copySet` for
   *  every anchor that needs one (fire-and-forget from the caller's side;
   *  each job dispatches its own follow-up transaction once it resolves).
   *  Returns whether the synchronous half changed the doc. */
  reconcile(editor: Editor, deps: MutationPasteDeps): boolean {
    const isManuscript = deps.isManuscript();
    const anchors: { pos: number; anchorId: string; setId: string }[] = [];
    const closes: { pos: number; closeId: string }[] = [];
    editor.state.doc.descendants((node, pos) => {
      if (node.type.name === "mutation") {
        anchors.push({ pos, anchorId: String(node.attrs.anchorId ?? ""), setId: String(node.attrs.setId ?? "") });
      } else if (node.type.name === "mutationClose") {
        closes.push({ pos, closeId: String(node.attrs.closeId ?? "") });
      }
      return true;
    });

    const seenThisWalk = new Set<string>();
    const remap = new Map<string, string>(); // old anchor id (as pasted) -> new id
    const dropPositions: number[] = [];
    const copyJobs: { newAnchorId: string; originalSetId: string }[] = [];
    let tr = editor.state.tr;
    let changed = false;

    // A cut's ledger is consumed once per PASTE OPERATION, not per anchor —
    // several anchors cut together and pasted together all stay kept.
    const cutLedger =
      clipboardLedger && clipboardLedger.kind === "cut" && !clipboardLedger.consumed ? clipboardLedger : null;
    let cutLedgerUsed = false;

    for (const { pos, anchorId, setId } of anchors) {
      const isDup = anchorId !== "" && seenThisWalk.has(anchorId);
      if (anchorId) seenThisWalk.add(anchorId);
      const isNew = anchorId !== "" && !this.#known.has(anchorId);
      if (!isManuscript) {
        if (isNew || isDup) dropPositions.push(pos);
        continue;
      }
      if (!isNew && !isDup) continue; // an untouched, already-known anchor

      const isFirstCutPaste = !isDup && Boolean(cutLedger?.anchorIds.has(anchorId));
      if (isFirstCutPaste) {
        cutLedgerUsed = true;
        continue; // kept exactly as pasted — same anchor, same set
      }

      const isCopy = isDup || deps.knownProjectAnchorIds().has(anchorId) || Boolean(clipboardLedger?.anchorIds.has(anchorId));
      if (!isCopy) continue; // brand-new content with no known collision — kept as pasted

      const freshId = createMutationId();
      remap.set(anchorId, freshId);
      seenThisWalk.add(freshId);
      tr = tr.setNodeMarkup(tr.mapping.map(pos), undefined, { setId: "", anchorId: freshId });
      changed = true;
      if (setId) copyJobs.push({ newAnchorId: freshId, originalSetId: setId });
    }
    if (cutLedgerUsed && cutLedger) cutLedger.consumed = true;

    // Non-manuscript: drop every anchor that just arrived, highest position
    // first so earlier positions stay valid as we delete.
    for (const pos of dropPositions.sort((a, b) => b - a)) {
      const mapped = tr.mapping.map(pos);
      const node = tr.doc.nodeAt(mapped);
      if (node) {
        tr = tr.delete(mapped, mapped + node.nodeSize);
        changed = true;
      }
    }

    // Closes: repoint any `ref` that a remap above just gave a new id (a
    // close pasted together with its anchor, ADR-0095 §7) — a close is
    // otherwise left untouched (its own id collisions are cosmetic; nothing
    // addresses a close by id).
    if (remap.size > 0) {
      for (const { pos } of closes) {
        const mapped = tr.mapping.map(pos);
        const node = tr.doc.nodeAt(mapped);
        if (!node) continue;
        const ref = String(node.attrs.ref ?? "");
        const next = remap.get(ref);
        if (next && next !== ref) {
          tr = tr.setNodeMarkup(mapped, undefined, { ...node.attrs, ref: next });
          changed = true;
        }
      }
    }

    if (changed) editor.view.dispatch(tr);
    this.#known = collectMutationIds(editor);

    for (const job of copyJobs) this.#runCopyJob(editor, job, deps);

    return changed;
  }

  #runCopyJob(editor: Editor, job: { newAnchorId: string; originalSetId: string }, deps: MutationPasteDeps): void {
    deps
      .copySet(job.originalSetId)
      .then((result) => {
        const pos = findMutationNodePos(editor, job.newAnchorId);
        if (pos === null) return; // the pill was deleted meanwhile — nothing to fill in
        const node = editor.state.doc.nodeAt(pos);
        if (!node) return;
        editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, setId: result.entry.id }));
        this.#known.add(job.newAnchorId);
        if (result.dropped_rows.length > 0) {
          deps.onNotice?.(
            `Copied the mutation set, but left out: ${result.dropped_rows.map((r) => r.field).join(", ")} (no longer valid for this entity).`,
          );
        }
      })
      .catch(() => {
        deps.onNotice?.("Couldn't copy the mutation set for a pasted change — the pill is missing its set.");
      });
  }
}

// ---------- Labels ----------

/** A set's pill label (ADR-0095 §1): its title, or — for an untitled set — a
 *  count fallback in the shape the old per-row unit label used ("N
 *  changes"). The roster only carries `row_count`, not the rows themselves,
 *  so (unlike the pre-ADR-0095 label) a single-row untitled set can't show
 *  "field → value" here without a per-pill fetch. */
export function mutationSetLabel(entry: { title: string; row_count: number } | undefined): string {
  if (!entry) return "";
  if (entry.title) return entry.title;
  return entry.row_count === 1 ? "1 change" : `${entry.row_count} changes`;
}

/** Auto-label for one resolved record/row (#58/#65): the set's name if set,
 *  else `field → value` (add/remove show +/−). Used by the close picker's
 *  per-row list, which has real records (with field/value) to show. */
export function mutationRecordLabel(attrs: {
  name?: unknown;
  op?: unknown;
  field?: unknown;
  value?: unknown;
}): string {
  const name = String(attrs.name ?? "");
  if (name) return name;
  const op = String(attrs.op ?? "replace");
  const field = String(attrs.field ?? "");
  const value = String(attrs.value ?? "");
  if (op === "add") return `${field} +${value}`;
  if (op === "remove") return `${field} −${value}`;
  return `${field} → ${value}`;
}

// ---------- Reveal ----------

/** A temporary ring on a pill (#2124's review-item reveal) — mirrors the
 *  embedded-TODO highlight's timer, styled beside `.mutation-pill` in
 *  styles.css. Not a new resting state: just "you're here". */
export const MUTATION_PILL_REVEALED_CLASS = "mutation-pill-revealed";
const MUTATION_PILL_REVEAL_MS = 2400;

/** A composite record id `<anchor>.<row>` (ADR-0095 §3) names its anchor
 *  directly — anchor/row ids never contain a `.`, so splitting on the first
 *  one is exact. A bare id (an anchor id, or a legacy row id pre-migration)
 *  is returned as-is; `resolveMutationRevealAnchor` below handles the bare
 *  row-id case that needs a lookup. */
export function anchorIdFromRevealTarget(id: string): string {
  const dot = id.indexOf(".");
  return dot === -1 ? id : id.slice(0, dot);
}

/** Scroll a pill (keyed by ANCHOR id, ADR-0095 §4) into view and flash it.
 *  False (a no-op for the caller) when the pill isn't in the DOM: a deleted
 *  anchor, or the doc not loaded into `editorElement` yet (the caller queues
 *  in that case). */
export function revealMutationPill(editorElement: HTMLElement, id: string): boolean {
  const anchorId = anchorIdFromRevealTarget(id);
  const target = editorElement.querySelector<HTMLElement>(`[data-mutation-id="${CSS.escape(anchorId)}"]`);
  if (!target) return false;
  target.classList.add(MUTATION_PILL_REVEALED_CLASS);
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  window.setTimeout(() => target.classList.remove(MUTATION_PILL_REVEALED_CLASS), MUTATION_PILL_REVEAL_MS);
  return true;
}

/** Resolve a reveal target that might be a BARE ROW id (ADR-0095 §3: "a row
 *  id finds the anchor whose set holds that row... the reveal uses the
 *  anchor in the open scene, else the first in manuscript order") to its
 *  anchor id. A composite id resolves locally with no fetch. */
export async function resolveMutationRevealAnchor(
  getEntityMutations: (entityId: string) => Promise<{ items: MutationMarkerRecord[] }>,
  entityId: string,
  id: string,
  sceneId: string,
): Promise<string> {
  if (id.includes(".")) return anchorIdFromRevealTarget(id);
  try {
    const records = (await getEntityMutations(entityId)).items;
    const matches = records.filter((r) => r.row_id === id || r.marker_id === id || r.anchor_id === id);
    if (matches.length === 0) return id;
    const inScene = matches.find((r) => r.scene_id === sceneId);
    const hit = inScene ?? matches[0];
    return hit.anchor_id || hit.unit_id || id;
  } catch {
    return id;
  }
}

// ---------- C2: the `/mutate` authoring dialogs' draft shape ----------

/** One field change inside a mutation unit — the authoring dialog's row
 *  shape, unchanged since #69. */
export interface MutationRowDraft {
  id?: string | null;
  field: string;
  op?: string;
  value: string;
}

/** An authored change from MutationAuthoringForm: one entity, N rows. C2
 *  rebuilds what this becomes (a mutation-SET create/save + `insertAnchor`,
 *  ADR-0095 §6) — kept only as the dialog's own draft shape so it still
 *  compiles. */
export interface MutationUnitDraft {
  markerId?: string | null;
  entity: string;
  name?: string;
  group?: string;
  rows: MutationRowDraft[];
}

// C2: ADR-0095 §6 rebuilds `/mutate` authoring end-to-end — creating a set
// (`api.createMutationSetEntry`/`saveMutationSetEntry`) and anchoring it
// (`insertAnchor` above) rather than writing entity/rows/name straight into
// the pill, which no longer has attrs for any of them (§1: `{ setId,
// anchorId }` only). Until that lands this is a deliberate no-op —
// MutationDialogs/MutationAuthoringForm still compile and close normally,
// they just don't write a pill.
export function applyMutationUnitDraft(_editor: Editor, _draft: MutationUnitDraft): void {}
