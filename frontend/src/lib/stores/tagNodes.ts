// Tag-node domain store (ADR-0082 slice 1) — the successor of `knownTagsStore`
// (`stores/tags.ts`, the legacy name/colour registry): a roster of real `tag`
// kind nodes across the merged chain, mirrored server-side. `writable` for
// legacy-safe reads (see docs/frontend-architecture.md), matching the sibling
// store's shape.

import { derived, get, writable } from "svelte/store";
import { api } from "@/lib/api";
import type { MetadataSchema, MetadataValue, TagEntry } from "@/lib/types";
import { createTargetFor } from "@/lib/utils/pickerCreate";

export const tagNodesStore = writable<TagEntry[]>([]);

// Monotonic guard so an overlapping refresh (a save's refresh racing a
// delete's, or two rapid tag-manager edits) can't land an older response
// over a newer one — mirrors `aiSpend`'s `#seq` (`stores/aiSpend.svelte.ts`).
let latest = 0;

// Refresh swallows errors — backend may be offline, or (since
// `projectSession.loadMachineSettings` now awaits this on every app boot)
// not listening yet — and leaves the previous roster in place, matching
// `refreshAssistantEntries` (`stores/assistants.ts`). A throw here would
// otherwise abort `rehydrate()`/`startCreateWizard()` before the wizard even
// opens, and make `clearProjectData`'s fire-and-forget call an unhandled
// rejection.
export async function refreshTagNodes(): Promise<void> {
  const seq = ++latest;
  try {
    const tags = (await api.listTagEntries()).tags;
    if (seq !== latest) return; // superseded by a later refresh
    tagNodesStore.set(tags);
  } catch {
    // Leave previous list in place.
  }
}

export function clearTagNodes(): void {
  tagNodesStore.set([]);
}

// ADR-0082 §2 / P3 (round 2): land a just-created (or just-saved) tag into
// the roster immediately, ahead of the next `refreshTagNodes()` — a create's
// own POST response is authoritative for its own entry, so the picker that
// asked for it (and `tagById`/`tagTitleById`) don't have to wait on a
// separate, best-effort GET that might itself fail. Replaces an existing
// entry with the same id (a re-save) or inserts a new one, keeping the same
// `(title.lower(), id)` order `list_tag_entries` (`tag_nodes.py`) sorts by,
// so a later refresh reconciles to the identical order rather than visibly
// re-shuffling the roster.
export function upsertTagNode(entry: TagEntry): void {
  const key = (t: TagEntry) => [t.title.toLowerCase(), t.id] as const;
  const [entryTitle, entryId] = key(entry);
  const rest = get(tagNodesStore).filter((t) => t.id !== entry.id);
  const insertAt = rest.findIndex((t) => {
    const [title, id] = key(t);
    return title > entryTitle || (title === entryTitle && id > entryId);
  });
  tagNodesStore.set(
    insertAt === -1 ? [...rest, entry] : [...rest.slice(0, insertAt), entry, ...rest.slice(insertAt)],
  );
}

// Id -> entry, derived once so every by-id consumer (ReferencePicker's
// `resolveRefById`, `tagTitleById` below) shares one Map instead of each
// re-deriving its own from the roster array.
export const tagById = derived(tagNodesStore, (tags) => {
  const map = new Map<string, TagEntry>();
  for (const tag of tags) map.set(tag.id, tag);
  return map;
});

// Tags without `merged_into` — the live vocabulary a picker/roster/create
// gesture may offer (ADR-0082 §5). A merged tag left every picker the moment
// it merged; the governance surface (TagsPane) still shows it, unfiltered,
// under "Merged".
export const liveTags = derived(tagNodesStore, (tags) => tags.filter((tag) => !tag.merged_into));

// The pure chain-follow: `id`, following every `merged_into` redirect over
// `byId` to its survivor — identity when `id` was never merged, or when it
// names a tag outside the roster (ADR-0082 §5). Cycle-guarded the same way
// the backend's `NodeIndex.canonical_id` is: a malformed loop degrades to
// "stop at the first repeat" rather than hanging. Public (not just
// `canonicalTagId` below) so a REACTIVE caller — one already holding a live
// `$tagById` read, e.g. `ViewNodeList`/`ViewBodyView`'s `canonicalId` prop —
// can apply it without going through `get()`, which would silently opt the
// caller out of Svelte's dependency tracking.
export function canonicalIdIn(byId: ReadonlyMap<string, TagEntry>, id: string): string {
  const seen = new Set([id]);
  let current = id;
  for (;;) {
    const next = byId.get(current)?.merged_into;
    if (!next || !byId.has(next) || seen.has(next)) return current;
    seen.add(next);
    current = next;
  }
}

// `get(tagById)` snapshot convenience for a non-reactive caller (a plain
// event handler, `findTagByTitle`-adjacent code) — never inside a `$derived`,
// where `canonicalIdIn($tagById, id)` is what tracks correctly.
export function canonicalTagId(id: string): string {
  return canonicalIdIn(get(tagById), id);
}

// Id -> title, for resolving a tag reference's chip/bucket label (§3 of the
// ADR: the frontend keeps a tag roster store so `entity_ref`/`entity_ref_list`
// values pointing at a tag resolve to a title instead of a raw id). A merged
// id maps to the SURVIVOR's title (§5) — `canonicalIdIn` is followed before
// the title lookup, so a carrier that has not been re-saved yet still shows
// the tag it now reads as.
export const tagTitleById = derived(tagById, (byId) => {
  const map = new Map<string, string>();
  for (const id of byId.keys()) {
    const survivor = byId.get(canonicalIdIn(byId, id));
    if (survivor) map.set(id, survivor.title);
  }
  return map;
});

// ADR-0082 §2 / F3: case-insensitive title resolution over the LIVE roster,
// ahead of a create — a same-title tag one hop up the merged chain (or
// created moments ago by a sibling save) is referenced, not duplicated. A
// merged tag is skipped (§5): typing its old name must mint or match the
// survivor, never resurrect the redirect. `entryType` narrows to one
// vocabulary when given (a picker source names exactly one when
// `create_missing` is eligible, F1); omitted, any vocabulary matches.
export function findTagByTitle(title: string, entryType?: string): TagEntry | undefined {
  const needle = title.trim().toLowerCase();
  if (!needle) return undefined;
  return get(liveTags).find(
    (tag) => tag.title.trim().toLowerCase() === needle && (!entryType || tag.entry_type === entryType),
  );
}

// ADR-0082 §2 (round 2, Y3): the ONE "resolve or mint" sequence — an existing
// title wins over minting a duplicate (case-insensitive, `findTagByTitle`),
// else POST and land the response in the roster (`upsertTagNode`) BEFORE
// returning, so the caller's very next lookup already sees it. Two callers
// share this exact sequence so neither can drift from the other's rule:
// `ReferencePicker.handleCreate` (the picker's own "Create ‹x›" row) and
// `resolveAdoptedTagItem` below (an accepted AI tag-title flip, #1797). Can
// reject (a `createTagEntry` failure) — callers decide what "partial" means
// for them; this makes no attempt to roll anything back (there is nothing TO
// roll back — a landed create is a real node).
export async function resolveOrCreateTag(
  title: string,
  entryType: string,
  createLayerId: string | null,
): Promise<TagEntry> {
  const existing = findTagByTitle(title, entryType);
  if (existing) return existing;
  const created = await api.createTagEntry(title, entryType, null, createLayerId);
  upsertTagNode(created);
  return created;
}

// ADR-0082 §2 / #1797 / #1799: resolve one AI-proposed tag flip ITEM at
// ACCEPT time — the validator only resolved titles matching an EXISTING tag
// (leaving anything else as a plain string, never minting one), so an
// accepted flip's value can still carry bare titles. "Already an id" is
// checked by ENTRY_TYPE, not mere roster membership (round 2, Y3): a bare
// title that happens to collide with some OTHER vocabulary's real id must
// still resolve/mint against `entryType`, not pass through as if it were
// already the right tag.
async function resolveAdoptedTagItem(
  item: string,
  entryType: string,
  createLayerId: string | null,
): Promise<string> {
  if (get(tagById).get(item)?.entry_type === entryType) return item; // already a resolved id
  const tag = await resolveOrCreateTag(item, entryType, createLayerId);
  return tag.id;
}

// The field-level counterpart: every item of an ACCEPTED tag-vocabulary
// flip's value, resolved to an id (minting what's still a bare title).
// Sequential, not `Promise.all` — a low-cardinality list (a handful of tags),
// and sequential means (a) the second occurrence of a still-unminted title
// within the SAME field sees the first's mint via `upsertTagNode` rather than
// racing it into a duplicate, and (b) a rejection stops the loop AT that item
// — every item resolved before it stays resolved (any tag it minted is a
// real, roster-visible node now; nothing here rolls it back), the ones after
// it are never attempted, and the rejection propagates to the caller
// (`onAdoptFields`, `NodeEditor.svelte`) so the WHOLE field writes nothing and
// the review stays open (`EntryProposalController.commit`, round 2 Y1). Non-
// string items are dropped (defensive; the validator already only ever
// leaves strings in this field). Called from the host's `onAdoptFields` —
// REJECTING the flip never calls this, so nothing is minted for a proposal
// the author didn't adopt.
export async function resolveAdoptedTagFieldValue(
  value: unknown,
  entryType: string,
  createLayerId: string | null,
): Promise<string[]> {
  if (!Array.isArray(value)) return [];
  const resolved: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || !item.trim()) continue;
    resolved.push(await resolveAdoptedTagItem(item.trim(), entryType, createLayerId));
  }
  return resolved;
}

// The ONE accept-time tag resolution every proposal→metadata path calls: for
// each field in `fields` that is a `create_missing`-tag-shaped picker field
// (`createTargetFor` — kind `"tag"`), resolves/mints its value in place via
// `resolveAdoptedTagFieldValue` above; every other field is left untouched.
// Mutates `fields` (the caller's own draft/proposal object) rather than
// returning a copy, matching both callers' existing loop shape. Two callers
// share this: `NodeEditor.svelte`'s `onAdoptFields` (adopting a flip into an
// EXISTING entry) and `treeActions.svelte.ts`'s `#mintFromDraft` (#1821 —
// the same resolution at create-from-draft time). A third accept path must
// call this too, not re-derive the loop.
export async function resolveAdoptedTagFields(
  fields: Record<string, MetadataValue>,
  schema: MetadataSchema | null | undefined,
  createLayerId: string | null,
): Promise<void> {
  for (const key of Object.keys(fields)) {
    const field = schema?.fields[key];
    const target = field ? createTargetFor(field.picker_config, schema) : null;
    if (target?.kind !== "tag") continue;
    fields[key] = await resolveAdoptedTagFieldValue(fields[key], target.entryType, createLayerId);
  }
}
