// #2437: clearing a list-valued rail field (tags, a ref list) drops every
// member at once, and rail metadata edits are not undoable (#2438) — so the
// reset gesture on a non-empty list always asks first, naming what goes.
// Scalar fields keep the one-click reset: one value is cheap to retype.
//
// Pure, so the wording and the "does this need asking?" rule are unit-tested
// without mounting the rail.

import type { MetadataValue } from "@/lib/metadataTypes";

export type ListClearPrompt = {
  title: string;
  message: string;
  details: string[];
};

// Null when the clear needs no confirmation (a scalar, or an empty list);
// otherwise the modal copy. `labelOf` resolves a member (a tag / node id) to
// its display title, falling back to the raw member.
export function listClearPrompt(
  fieldLabel: string,
  value: MetadataValue | undefined,
  labelOf: (member: string) => string | null,
): ListClearPrompt | null {
  if (!Array.isArray(value)) return null;
  const members = value.map((item) => String(item)).filter(Boolean);
  if (members.length === 0) return null;
  const count = members.length === 1 ? "1 value" : `all ${members.length} values`;
  return {
    title: `Clear ${fieldLabel}`,
    message: `Remove ${count} from ${fieldLabel}?`,
    details: members.map((member) => labelOf(member) ?? member),
  };
}
