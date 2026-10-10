// #2437: clearing a list-valued rail field (tags, a ref list) drops every
// member at once, and the rail's undo (#2438) lasts only the session — so the
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

// The modal lists at most this many members, then "…and N more".
export const LIST_CLEAR_DETAIL_CAP = 10;

// Null when the clear needs no confirmation (a scalar, or an empty list);
// otherwise the modal copy. `labelOf` resolves a member (a tag / node id) to
// its display title, falling back to the raw member. `revertsToInherited`: the
// same clear on a cascade-overridden field restores the inherited list rather
// than emptying it, so the copy says so instead of "remove".
export function listClearPrompt(
  fieldLabel: string,
  value: MetadataValue | undefined,
  labelOf: (member: string) => string | null,
  revertsToInherited = false,
): ListClearPrompt | null {
  if (!Array.isArray(value)) return null;
  const members = value.map((item) => String(item)).filter(Boolean);
  if (members.length === 0) return null;
  const shown = members.slice(0, LIST_CLEAR_DETAIL_CAP).map((member) => labelOf(member) ?? member);
  const hidden = members.length - shown.length;
  const details = hidden > 0 ? [...shown, `…and ${hidden} more`] : shown;
  if (revertsToInherited) {
    const these = members.length === 1 ? "the value" : `the ${members.length} values`;
    return {
      title: `Reset ${fieldLabel}`,
      message: `Replace ${these} set here with the inherited ${fieldLabel}?`,
      details,
    };
  }
  const count = members.length === 1 ? "1 value" : `all ${members.length} values`;
  return { title: `Clear ${fieldLabel}`, message: `Remove ${count} from ${fieldLabel}?`, details };
}
