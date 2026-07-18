// MACHINE-GENERATED from view-grammar.yaml by emit_ts.py — DO NOT EDIT.
// Edit the IDL and regenerate. See scripts/viewgrammar/README.md for the
// stable surface vs. what churns on a grammar change.

export type ViewLeafValue = string | { var: string };
export type ViewOperand = unknown | { var: string } | { field_of: ViewFieldOf };

export type ViewFieldPredicate = {
  key: string;
  op: "overlap" | "disjoint" | "set" | "unset";
  value?: ViewOperand;
};

export type ViewFieldOf = {
  of: ViewExpr;
  field: string;
};

export type ViewAnnotatePayload = {
  label?: string;
  color?: string;
  rank?: number;
};

export type ViewDifferenceOp = {
  keep: ViewExpr;
  remove: ViewExpr;
};

export type ViewNestMatch = {
  field: string;
  direction: "child_to_parent" | "parent_to_children";
  by: "ref" | "title";
};

export type ViewNestOp = {
  parents?: ViewExpr | null;
  children?: ViewExpr | null;
  match: ViewNestMatch;
  recursive?: boolean;
  id?: string;
};

export type ViewExpr = {
  union?: ViewExpr[];
  intersect?: ViewExpr[];
  difference?: ViewDifferenceOp;
  complement?: ViewExpr;
  nest?: ViewNestOp;
  annotate?: ViewAnnotatePayload;
  field_of?: ViewFieldOf;
  type?: ViewLeafValue;
  descendants_of?: ViewLeafValue;
  tagged?: ViewLeafValue;
  field?: ViewFieldPredicate;
  hand_picked?: string[];
  var?: string;
  orphans_of?: string;
  of?: ViewExpr;
  orphans_nest?: ViewNestOp;
};

// The single generated traversal (mirrors walkViewExpr).
export function children(e: ViewExpr): ViewExpr[] {
  const out: ViewExpr[] = [];
  for (const s of e.union ?? []) out.push(s);
  for (const s of e.intersect ?? []) out.push(s);
  if (e.difference?.keep) out.push(e.difference.keep);
  if (e.difference?.remove) out.push(e.difference.remove);
  if (e.complement) out.push(e.complement);
  if (e.nest?.parents) out.push(e.nest.parents);
  if (e.nest?.children) out.push(e.nest.children);
  if (e.field_of?.of) out.push(e.field_of.of);
  const _v_field = e.field?.value;
  if (_v_field && typeof _v_field === "object" && "field_of" in _v_field)
    out.push((_v_field as { field_of: ViewFieldOf }).field_of.of);
  if (e.of) out.push(e.of);
  if (e.orphans_nest?.parents) out.push(e.orphans_nest.parents);
  if (e.orphans_nest?.children) out.push(e.orphans_nest.children);
  return out;
}
