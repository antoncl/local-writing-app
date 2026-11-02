// Where proofreading applies (ADR-0102 §1). The one predicate the prose body,
// the long-text fields and the footer toggle all ask: code, templates and chat
// are not prose and stay unchecked.
import type { DocumentKind } from "@/lib/documentTypes";

const UNCHECKED: ReadonlySet<DocumentKind> = new Set<DocumentKind>(["chat", "prompt", "snippet", "assistant", "view"]);

export function proofreadable(kind: DocumentKind): boolean {
  return !UNCHECKED.has(kind);
}
