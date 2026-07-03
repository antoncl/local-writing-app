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

export type PromptSurface = "append_to_body" | "replace_selection" | "chat_panel";

// A snapshot of the reactive data the resolvers read. ProseBodyView builds
// this as a `$derived` and passes it (or a getter onto it) at each call.
export interface PromptResolutionContext {
  metadataSchema: MetadataSchema | null;
  promptEntries: PromptEntrySummary[];
  loreEntries: LoreEntrySummary[];
  availableScenes: { id: string; title: string }[];
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

export function promptEntriesForSurface(
  ctx: PromptResolutionContext,
  surface: PromptSurface,
): PromptEntrySummary[] {
  if (!ctx.metadataSchema) return [];
  return ctx.promptEntries
    .filter((entry) => effectiveOutputKind(ctx, entry) === surface)
    .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
}

export function promptEntryDescription(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary,
): string {
  return ctx.metadataSchema?.entry_types[entry.entry_type]?.name ?? entry.entry_type;
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

  type Cand = { id: string; kind: "lore" | "scene"; title: string; entry_type?: string };
  const candidates: Cand[] = [];

  if (!wantKind || wantKind === "lore") {
    for (const lore of ctx.loreEntries) {
      if (lore.title.toLowerCase() !== lower) continue;
      if (wantEntryType && lore.entry_type !== wantEntryType) continue;
      candidates.push({ id: lore.id, kind: "lore", title: lore.title, entry_type: lore.entry_type });
    }
  }
  if (!wantKind || wantKind === "scene") {
    for (const sc of ctx.availableScenes) {
      if (sc.title.toLowerCase() !== lower) continue;
      candidates.push({ id: sc.id, kind: "scene", title: sc.title });
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

// True iff the prompt entry-type chain includes `roleplay` (so any
// future sub-type of roleplay still gets character-tagged on Accept).
export function isRoleplayPromptEntry(
  ctx: PromptResolutionContext,
  entry: PromptEntrySummary | null | undefined,
): boolean {
  if (!entry || !ctx.metadataSchema) return false;
  let cursor: string | undefined = entry.entry_type;
  const seen = new Set<string>();
  while (cursor && !seen.has(cursor)) {
    if (cursor === "prompt:roleplay") return true;
    seen.add(cursor);
    cursor = ctx.metadataSchema.entry_types[cursor]?.parent ?? undefined;
  }
  return false;
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
