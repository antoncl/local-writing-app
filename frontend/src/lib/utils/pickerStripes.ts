// Stripe-colour resolution for context-picker rows (ADR-0066/0068) — the one
// curved kind-stripe a NodeRow carries. `resolveColor` walks instance → type →
// kind, so a node's own `metadata.color` wins over the type/kind default (#1520).
// Extracted from NodePicker.svelte (file-size cap) as pure, schema-parameterized
// helpers.

import { resolveColor } from "@/lib/utils/colors";
import type { MetadataSchema } from "@/lib/types";

/** The resolved kind/sub-type hex for a ref, or null. No instance override. */
export function hexForRef(
  ref: { kind: string; entry_type?: string },
  schema: MetadataSchema | null | undefined,
): string | null {
  return resolveColor(null, ref.entry_type, ref.kind, schema)?.hex ?? null;
}

/** The stripe for a tree row keyed on entry_type alone (kind = the `kind:key`
 * prefix). A type with no colour (e.g. structural manuscript) yields null. */
export function stripeForType(
  entryType: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  if (!entryType) return null;
  return hexForRef({ kind: entryType.split(":")[0], entry_type: entryType }, schema);
}

/** Like stripeForType, but honours a node's own `metadata.color` (an instance
 * override) ahead of the type/kind default (#1520 — a custom-coloured node
 * otherwise showed the kind default). */
export function stripeForNode(
  instanceColor: string | null | undefined,
  entryType: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  const kind = entryType ? entryType.split(":")[0] : null;
  return resolveColor(instanceColor ?? null, entryType ?? null, kind, schema)?.hex ?? null;
}
