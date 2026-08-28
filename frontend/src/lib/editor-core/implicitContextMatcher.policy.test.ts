// ADR-0075 §7 / slice 4 — the over-promise guard.
//
// The highlight is a promise the entity will be in the model's context, so the
// matcher must not decorate entities the backend's detection drops. The backend
// name-matcher excludes `context_policy` of `never`/`manual_only` (only
// `auto`/`always` reach the model via detection); `compileMatcher` must mirror
// that so the on-screen promise matches what the backend delivers.

import { describe, expect, it } from "vitest";
import { compileMatcher } from "./implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

function entry(id: string, title: string, policy?: string): LoreEntrySummary {
  const metadata: Record<string, unknown> = { aliases: [] };
  if (policy) metadata.context_policy = policy;
  return { id, title, entry_type: "", metadata, body: "" } as LoreEntrySummary;
}

describe("implicitContextMatcher — context_policy over-promise guard", () => {
  it("skips never/manual_only entities and keeps auto/always/unset", () => {
    const entries = [
      entry("e_unset", "Alice"), // no policy → backend default is auto
      entry("e_auto", "Bob", "auto"),
      entry("e_always", "Carol", "always"),
      entry("e_never", "Dave", "never"),
      entry("e_manual", "Eve", "manual_only"),
    ];
    const matcher = compileMatcher(entries);
    const hitIds = new Set(
      matcher.scan("Alice, Bob, Carol, Dave, and Eve all met.").map((h) => h.entryId),
    );

    expect(hitIds.has("e_unset")).toBe(true);
    expect(hitIds.has("e_auto")).toBe(true);
    expect(hitIds.has("e_always")).toBe(true);
    expect(hitIds.has("e_never")).toBe(false);
    expect(hitIds.has("e_manual")).toBe(false);
  });
});
