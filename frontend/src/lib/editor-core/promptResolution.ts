// Prompt-resolution helpers shared between the editor's slash menu /
// selection toolbar (which live in ProseBodyView) and the AI suggestion
// pipeline (AiSuggestionController). Both need to resolve which prompt
// entries apply to a surface, fill positional slash args, and inspect a
// prompt's output kind / roleplay lineage — so the logic lives here as
// pure functions over a context snapshot rather than being duplicated or
// passed around as a bag of closures.

import { coerceInputValue } from "@/lib/utils/promptInputs";
import type {
  LoreEntrySummary,
  MetadataSchema,
  PromptEntrySummary,
  PromptInputDefinition,
} from "@/lib/types";

// The output dispositions a prompt can select (ADR-0054 §1), mirroring the
// backend `OUTPUT_KINDS`. A brainstorm is no longer a fifth surface — it is
// `chat_panel` + a `commit`, asked via `promptDeclaresCommit` below.
export type PromptSurface = "append_to_body" | "replace_selection" | "chat_panel";

// A snapshot of the reactive data the resolvers read. ProseBodyView builds
// this as a `$derived` and passes it (or a getter onto it) at each call.
export interface PromptResolutionContext {
  metadataSchema: MetadataSchema | null;
  promptEntries: PromptEntrySummary[];
  loreEntries: LoreEntrySummary[];
  availableScenes: { id: string; title: string }[];
  // Built-in Library prompts the writer hid in this project (ADR-0049 slice 3).
  // Filtered out of DISCOVERY (`promptEntriesForSurface`) only — the full
  // `promptEntries` is kept intact so `findPromptEntry` can still resolve a
  // prompt already referenced by id (e.g. a chat/mutation that uses a hidden one).
  hiddenPromptIds?: Set<string>;
}

export function effectiveOutputKind(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
): string | null {
  const definition = ctx.metadataSchema?.entry_types[entry.entry_type];
  const output = definition?.prompt?.context_strategy?.output;
  if (!output || typeof output.kind !== "string") return null;
  return output.kind;
}

// True iff the prompt declares a `commit` (ADR-0054 §2) — i.e. it is a brainstorm
// whose chat-panel output can be extracted to a target node as a reviewable patch.
// This is the routing question dispatch asks now, in place of the retired
// `output.kind === "entry_patch"`. A commit only rides on `chat_panel`, so the
// presence of the object is the whole test.
export function promptDeclaresCommit(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
): boolean {
  const definition = ctx.metadataSchema?.entry_types[entry.entry_type];
  return !!definition?.prompt?.context_strategy?.output?.commit;
}

// Drop the writer's hidden built-in Library prompts (ADR-0049 slice 3) from a
// roster. This is the shared seam every prompt-DISCOVERY surface routes through:
// the slash menu / toolbar / brainstorm bars via promptEntriesForSurface below,
// and the chat "Pick a prompt" list + NodePicker's snippet picker directly (#682)
// — so a hidden prompt leaves every surface a writer reaches for one from.
// Resolution BY ID (findPromptEntry, a chat's stored prompt, a reference map)
// deliberately does NOT call this: a hidden prompt already in use must still
// resolve, so the full roster is kept for those paths.
//
// Returns the input array UNCHANGED (same reference, no copy) when nothing is
// hidden, so callers must treat the result as read-only — filter/map it, never
// mutate in place. Every caller today does.
export function hidePromptEntries(
  entries: PromptEntrySummary[],
  hiddenPromptIds: Set<string> | undefined,
): PromptEntrySummary[] {
  if (!hiddenPromptIds || hiddenPromptIds.size === 0) return entries;
  return entries.filter((entry) => !hiddenPromptIds.has(entry.id));
}

// The shared discovery-roster skeleton: no schema → empty; else drop the writer's
// hidden built-ins, keep the entries matching `predicate`, sort by title. Both
// rosters below route through it so hidden-prompt handling and sort collation
// can't drift between surface-discovery and brainstorm-discovery.
function filterPromptRoster(
  ctx: PromptResolutionContext,
  predicate: (entry: PromptEntrySummary) => boolean,
): PromptEntrySummary[] {
  if (!ctx.metadataSchema) return [];
  return hidePromptEntries(ctx.promptEntries, ctx.hiddenPromptIds)
    .filter(predicate)
    .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
}

export function promptEntriesForSurface(
  ctx: PromptResolutionContext,
  surface: PromptSurface,
): PromptEntrySummary[] {
  return filterPromptRoster(ctx, (entry) => effectiveOutputKind(ctx, entry) === surface);
}

// The brainstorm prompts — those declaring a `commit` (ADR-0054 §2) — as a
// discovery roster, the commit-era replacement for
// `promptEntriesForSurface(ctx, "entry_patch")`. Used where "a committing
// prompt" specifically is wanted (Lore's Brainstorm affordance); the ＋New menu
// itself keys off `promptEntriesOfferedOn` (offer_on + chat_panel), where commit
// is orthogonal.
export function promptEntriesWithCommit(ctx: PromptResolutionContext): PromptEntrySummary[] {
  return filterPromptRoster(ctx, (entry) => promptDeclaresCommit(ctx, entry));
}

export function promptEntryDescription(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
): string {
  return ctx.metadataSchema?.entry_types[entry.entry_type]?.name ?? entry.entry_type;
}

// Walk `entryType`'s schema parent chain for `ancestor` (is-a). Without a schema,
// only an exact match holds. Mirrors `isRoleplayPromptEntry`'s ancestry walk.
function entryTypeIsA(
  ctx: PromptResolutionContext,
  entryType: string,
  ancestor: string,
): boolean {
  if (!ctx.metadataSchema) return entryType === ancestor;
  let cursor: string | undefined = entryType;
  const seen = new Set<string>();
  while (cursor && !seen.has(cursor)) {
    if (cursor === ancestor) return true;
    seen.add(cursor);
    cursor = ctx.metadataSchema.entry_types[cursor]?.parent ?? undefined;
  }
  return false;
}

// True iff `entry` declares it should be offered on a subject of schema type
// `entryType` (ADR-0054 §4/S4) — one of its `offer_on` targets is an
// ancestor-or-self of `entryType`. This is the author's explicit "show this
// prompt on…" allow-list, and it REPLACES the pre-S4 inference from context_pick
// input targets: `offer_on` (where a prompt is offered) is now decoupled from the
// input targets (what entity it pulls in). No declaration ⇒ offered nowhere
// (opt-in, no implicit everywhere-match), so each conversation prompt names its
// subjects; a lore entry offers the lore revise prompt, a plot card the plot-card
// one, a character both the revise prompt and impersonate — never cross.
export function promptOffersOn(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
  entryType: string | null | undefined,
): boolean {
  if (!entryType) return false;
  return (entry.offer_on ?? []).some((target) => entryTypeIsA(ctx, entryType, target));
}

// The prompts offered as a "＋New" conversation on a subject of type `entryType`:
// a `chat_panel` disposition (the only kind that surfaces a conversation, and the
// only kind that menu launches — the eligibility axis) whose `offer_on` admits
// this subject (the applicability axis). A committing brainstorm and a plain
// conversation (e.g. impersonate) both qualify — commit is orthogonal. Callers
// pass the result to `buildPromptMenuTree` for the "/" grouping.
export function promptEntriesOfferedOn(
  ctx: PromptResolutionContext,
  entryType: string | null | undefined,
): PromptEntrySummary[] {
  return filterPromptRoster(
    ctx,
    (entry) => effectiveOutputKind(ctx, entry) === "chat_panel" && promptOffersOn(ctx, entry, entryType),
  );
}

export function effectivePromptInputs(entry: PromptEntrySummary): PromptInputDefinition[] {
  return entry.inputs ?? [];
}

export function findPromptEntry(
  ctx: PromptResolutionContext,
  entryId: string | null,
): PromptEntrySummary | null {
  if (!entryId) return null;
  return ctx.promptEntries.find((entry) => entry.id === entryId) ?? null;
}

export function defaultPromptForSurface(
  ctx: PromptResolutionContext,
  surface: "append_to_body" | "replace_selection",
): PromptEntrySummary | null {
  return promptEntriesForSurface(ctx, surface)[0] ?? null;
}

// Resolve a positional-string token against a context_pick input.
export function resolveContextPickToken(
  ctx: PromptResolutionContext,
  token: string,
  target: { kind?: string; entry_type?: string } | null | undefined,
): string | null {
  const lower = token.toLowerCase();
  const wantKind = target?.kind;
  const wantEntryType = target?.entry_type;

  type Cand = { id: string; kind: "lore" | "manuscript"; title: string; entry_type?: string };
  const candidates: Cand[] = [];

  if (!wantKind || wantKind === "lore") {
    for (const lore of ctx.loreEntries) {
      if (lore.title.toLowerCase() !== lower) continue;
      if (wantEntryType && lore.entry_type !== wantEntryType) continue;
      candidates.push({ id: lore.id, kind: "lore", title: lore.title, entry_type: lore.entry_type });
    }
  }
  if (!wantKind || wantKind === "manuscript") {
    for (const sc of ctx.availableScenes) {
      if (sc.title.toLowerCase() !== lower) continue;
      candidates.push({ id: sc.id, kind: "manuscript", title: sc.title });
    }
  }

  if (candidates.length !== 1) return null;
  const c = candidates[0];
  const ref: { id: string; kind: string; title: string; entry_type?: string } = {
    id: c.id,
    kind: c.kind,
    title: c.title,
  };
  if (c.entry_type) ref.entry_type = c.entry_type;
  return JSON.stringify([ref]);
}

export function resolvePromptPositionalArgs(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
  args: string[],
): {
  inputs: Record<string, unknown> | undefined;
  satisfied: boolean;
  unresolved: Array<{ name: string; label: string; token: string }>;
} {
  const declared = effectivePromptInputs(entry);
  if (declared.length === 0 || args.length === 0) {
    return { inputs: undefined, satisfied: false, unresolved: [] };
  }
  const inputs: Record<string, unknown> = {};
  const filledNames = new Set<string>();
  const unresolved: Array<{ name: string; label: string; token: string }> = [];
  const limit = Math.min(declared.length, args.length);
  for (let i = 0; i < limit; i++) {
    const input = declared[i];
    const raw = args[i];
    const label = input.label || input.name;
    if (input.type === "context_pick") {
      const target = input.target as { kind?: string; entry_type?: string } | null | undefined;
      const resolved = resolveContextPickToken(ctx, raw, target);
      if (resolved === null) {
        unresolved.push({ name: input.name, label, token: raw });
        continue;
      }
      inputs[input.name] = resolved;
      filledNames.add(input.name);
    } else {
      const coerced = coerceInputValue(raw, input.type);
      if (coerced === null || coerced === "") {
        unresolved.push({ name: input.name, label, token: raw });
        continue;
      }
      inputs[input.name] = coerced;
      filledNames.add(input.name);
    }
  }
  const missingRequired = declared.some(
    (input) => input.required && !filledNames.has(input.name),
  );
  return {
    inputs,
    satisfied: !missingRequired && unresolved.length === 0,
    unresolved,
  };
}

// The accept-time mark-stamp a prompt's type declares (#954, Lever 2), or null.
// Present ⇒ accepting an inline suggestion from this prompt wraps it in `mark`,
// keyed to the lore id in the context_pick input `fromInput`. This REPLACES the
// `entry_type == "prompt:roleplay"` branch: the behaviour is read off the type's
// declared capability, exactly as `promptDeclaresCommit` reads `output.commit` —
// so a roleplay sub-type still stamps (it inherits the type's `on_accept`) without
// any name being special-cased in code.
export function promptOnAccept(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary | null | undefined,
): { mark: string; fromInput: string } | null {
  if (!entry) return null;
  const onAccept =
    ctx.metadataSchema?.entry_types[entry.entry_type]?.prompt?.context_strategy?.output?.on_accept;
  if (!onAccept?.mark || !onAccept.from_input) return null;
  return { mark: onAccept.mark, fromInput: onAccept.from_input };
}

// The mutation resolution scene from a `scene_ref` input (ADR-0012): the first
// scene_ref input with a non-empty value wins. Returns "" when the prompt has
// no scene_ref input or it is unset — the backend then falls back to the
// caller's target scene. Callers pass this as `resolution_scene_id`.
export function resolutionSceneIdFromInputs(
  entry: PromptEntrySummary | null | undefined,
  inputs: Record<string, unknown> | undefined,
): string {
  if (!entry || !inputs) return "";
  for (const def of entry.inputs ?? []) {
    if (def.type !== "scene_ref") continue;
    const value = inputs[def.name];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

// Pull the first lore id from a context_pick input value.
export function characterIdFromInputValue(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed.startsWith("[")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const first = parsed[0];
    if (first && typeof first === "object" && typeof first.id === "string") return first.id;
    return null;
  } catch {
    return null;
  }
}
