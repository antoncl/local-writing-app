// Prompt-resolution helpers shared between the editor's slash menu /
// selection toolbar (which live in ProseBodyView) and the AI suggestion
// pipeline (AiSuggestionController). Both need to resolve which prompt
// entries apply to a surface, fill positional slash args, and inspect a
// prompt's output handler / roleplay lineage — so the logic lives here as
// pure functions over a context snapshot rather than being duplicated or
// passed around as a bag of closures.

import { coerceInputValue } from "@/lib/utils/promptInputs";
import {
  inlineDestinationFor,
  outputHandlerFor,
  type InlineDestination,
} from "@/lib/editor-core/outputHandlers";
import type {
  LoreEntrySummary,
  MetadataSchema,
  PromptContextStrategy,
  PromptEntrySummary,
  PromptInputDefinition,
} from "@/lib/types";

// The DISCOVERY surface a prompt is offered on, derived from its output handler
// (ADR-0065): the two inline destinations (`cursor` = continue, `selection` =
// revise) plus `conversation` (any non-inline invocable prompt — a brainstorm or a
// general chat). Replaces the old disposition triple; `promptSurfaceFor` derives it.
export type PromptSurface = InlineDestination | "conversation";

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

// The discovery surface a `context_strategy` implies (ADR-0065). The presence of a
// `context_strategy` IS the invocation contract: a `snippet` (imported by name, never
// run) has none → null; every runnable prompt has one. Within that, the `inline`
// handler resolves to its destination (cursor/selection); any other REGISTERED handler
// (`extract_to_node`) or a handler-less `general` chat is a `conversation`. A non-empty
// but unregistered handler is misconfigured → null (invocable on no surface). Factored
// out of `promptSurfaceFor` so a caller holding a raw strategy — the prompt editor
// reading the open node's own type — shares the exact rule.
export function surfaceForStrategy(
  strategy: PromptContextStrategy | null | undefined,
): PromptSurface | null {
  if (!strategy) return null;
  const output = strategy.output ?? null;
  const handler = outputHandlerFor(output);
  if (handler) return handler.key === "inline" ? inlineDestinationFor(output) : "conversation";
  return output?.handler ? null : "conversation";
}

// The discovery surface a prompt is offered on. REPLACES the old `effectiveOutputKind`
// read every discovery filter used.
export function promptSurfaceFor(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
): PromptSurface | null {
  return surfaceForStrategy(
    ctx.metadataSchema?.entry_types[entry.entry_type]?.prompt?.context_strategy,
  );
}

// True iff the prompt declares a `commit` (ADR-0054 §2) — i.e. it is an
// `extract_to_node` brainstorm whose output can be extracted to a target node as a
// reviewable patch. This is the routing question dispatch asks now, in place of the
// retired `output.kind === "entry_patch"`. A commit only rides on `extract_to_node`,
// so the presence of the object is the whole test.
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
  return filterPromptRoster(ctx, (entry) => promptSurfaceFor(ctx, entry) === surface);
}

// The brainstorm prompts — those declaring a `commit` (ADR-0054 §2) — as a
// discovery roster, the commit-era replacement for the retired `entry_patch`
// surface. Used where "a committing prompt" specifically is wanted (Lore's
// Brainstorm affordance); the ＋New menu itself keys off `promptEntriesOfferedOn`
// (offer_on + the `conversation` surface), where commit is orthogonal.
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
// a `conversation` surface (the only surface that menu launches — the eligibility
// axis) whose `offer_on` admits this subject (the applicability axis). A committing
// brainstorm and a plain conversation (e.g. impersonate) both qualify — the commit is
// orthogonal, and both are non-inline so both are `conversation`. Callers pass the
// result to `buildPromptMenuTree` for the "/" grouping.
export function promptEntriesOfferedOn(
  ctx: PromptResolutionContext,
  entryType: string | null | undefined,
): PromptEntrySummary[] {
  return filterPromptRoster(
    ctx,
    (entry) => promptSurfaceFor(ctx, entry) === "conversation" && promptOffersOn(ctx, entry, entryType),
  );
}

// The prompt's EFFECTIVE inputs (ADR-0061): its own declared inputs plus the
// transitive union of every `prompt:snippet` it `{% include %}`s. The backend's
// one resolver computes this (`effective_inputs` on the summary); every
// invocation surface — the run/invocation dialog, chat's inputs strip — reads it
// here so a snippet's fields flow to all of them without hand-copying. Falls
// back to own `inputs` for a summary the backend didn't populate (equal anyway
// for a prompt with no includes).
export function effectivePromptInputs(entry: PromptEntrySummary): PromptInputDefinition[] {
  return entry.effective_inputs ?? entry.inputs ?? [];
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
  surface: "cursor" | "selection",
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
