// Reproduce-today proof (TS side, #277 / ADR-0041 Decision G): the generated grammar types
// are STRUCTURALLY IDENTICAL to the hand-written frontend/src/lib/types.ts. If any pair drifts,
// tsc fails the corresponding `Expect<Equal<...>>` below. Run via tsconfig.check.json.
import type * as Hand from "../../frontend/src/lib/types";
import type * as Gen from "./generated_grammar";

// Exact type equality (invariant — catches optional/nullable/shape differences both ways).
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Expect<T extends true> = T;

// One assertion per type present in both. ViewExpr transitively covers ViewDifferenceOp (inline
// in the hand-written type; a transparent alias in the generated one).
export type _ViewExpr = Expect<Equal<Gen.ViewExpr, Hand.ViewExpr>>;
export type _FieldPredicate = Expect<Equal<Gen.ViewFieldPredicate, Hand.ViewFieldPredicate>>;
export type _FieldOf = Expect<Equal<Gen.ViewFieldOf, Hand.ViewFieldOf>>;
export type _Operand = Expect<Equal<Gen.ViewOperand, Hand.ViewOperand>>;
export type _LeafValue = Expect<Equal<Gen.ViewLeafValue, Hand.ViewLeafValue>>;
export type _AnnotatePayload = Expect<Equal<Gen.ViewAnnotatePayload, Hand.ViewAnnotatePayload>>;
export type _NestMatch = Expect<Equal<Gen.ViewNestMatch, Hand.ViewNestMatch>>;
export type _NestOp = Expect<Equal<Gen.ViewNestOp, Hand.ViewNestOp>>;
