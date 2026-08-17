// The built-in views a kind ships (ADR-0051 S6 follow-up). Generalizes the
// single per-kind system default into an ordered list of read-only views:
//   [0] the roster default (selected when nothing is chosen — the id the fold
//       state materializes to, `view_default_<kind>`), then any curated extras.
// The switcher renders each read-only (Duplicate-to-edit, never Edit/Delete);
// `paneViews.specFor` resolves an extra's id to its spec here (extras are
// frontend-synthesized, not backend nodes — a filter/roster carries no fold
// state to persist). Only `chat` ships an extra today; every other kind keeps
// its single default, so `defaultView` parity with the backend is untouched.

import { defaultView, kindUniverseExpr } from "@/lib/views/evaluateView";
import { SEED_DISPOSITION_FIELD } from "@/lib/views/chatNodes";
import { REVISE_ENTITIES_DISPOSITION_LABEL } from "@/lib/views/promptNodes";
import type { MetadataSchema, ViewSpec } from "@/lib/types";

export type BuiltinView = { id: string; title: string; spec: ViewSpec };

const BUILTIN_EXTRA_PREFIX = "view_builtin_";

// An extra built-in view (not the roster default) — selected by its own id and
// treated as a valid selection by paneViews even though it is not a saved node.
export function isBuiltinExtraViewId(id: string): boolean {
  return id.startsWith(BUILTIN_EXTRA_PREFIX);
}

// "Openable chats": hides the brainstorm chats — those whose seed prompt has the
// "Revise entities" disposition (an extract_to_node prompt that declares a `commit`,
// ADR-0054 §2 / ADR-0065) — keeping plain chats ("Chat") and freeform ones. It filters on the
// seed's disposition label, the same vocabulary the Prompts shelf uses, so a user
// can rebuild or invert this view in the designer (#960). Blacklist, not whitelist:
// a freeform chat has no seeding prompt and so carries "", and must stay openable (a
// whitelist would drop it). `disjoint` is the grammar's set-exclusion op (no
// `eq`/`in`). The roster comes from `kindUniverseExpr` (the same seam `defaultView`
// uses), not a hardcoded FQN — so both chat built-ins resolve the root identically,
// including the schema-less `chat:base` fallback during the schema-load window.
function openableChatsSpec(schema?: MetadataSchema | null): ViewSpec {
  return {
    kind: "chat",
    expr: {
      filter: {
        of: kindUniverseExpr("chat", schema),
        pred: {
          field: { key: SEED_DISPOSITION_FIELD, op: "disjoint", value: [REVISE_ENTITIES_DISPOSITION_LABEL] },
        },
      },
    },
    sort: { by: "manual" },
  };
}

export function builtinViews(kind: string, schema?: MetadataSchema | null): BuiltinView[] {
  const base: BuiltinView = {
    id: `view_default_${kind}`,
    title: kind === "chat" ? "All chats" : "Default view",
    spec: defaultView(kind, schema),
  };
  if (kind === "chat") {
    return [base, { id: `${BUILTIN_EXTRA_PREFIX}chat_openable`, title: "Openable chats", spec: openableChatsSpec(schema) }];
  }
  return [base];
}

// The spec for a built-in view id (default or extra), or null if not built-in.
export function builtinSpecFor(kind: string, id: string, schema?: MetadataSchema | null): ViewSpec | null {
  return builtinViews(kind, schema).find((view) => view.id === id)?.spec ?? null;
}
