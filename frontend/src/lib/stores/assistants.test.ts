import { describe, expect, it } from "vitest";
import { get } from "svelte/store";
import type { AssistantEntrySummary } from "@/lib/types";
import { assistantEntriesStore, defaultAssistantIdStore } from "@/lib/stores/assistants";

const A = (id: string, listed: string): AssistantEntrySummary =>
  ({
    id,
    title: id,
    entry_type: "assistant:assistant",
    metadata: {},
    computed_metadata: { listed, position: 0 },
  }) as AssistantEntrySummary;

// ADR-0024 Amendment 1 (#333). The roster carries un-listed entries so nothing
// becomes unreachable in the Assistants pane, which means `$entries[0]` stopped
// meaning "top of my roster" — and an un-listed assistant sorts first often
// enough that un-listing became a way to make the app START using something.
// A mutation reverting this to `$entries[0]` survived the whole suite until
// this file existed.
describe("defaultAssistantIdStore", () => {
  it("skips an un-listed assistant that sorts first", () => {
    assistantEntriesStore.set([A("gone", "unlisted"), A("keep", "listed")]);
    expect(get(defaultAssistantIdStore)).toBe("keep");
  });

  it("is empty when nothing is listed, rather than guessing", () => {
    assistantEntriesStore.set([A("gone", "unlisted")]);
    expect(get(defaultAssistantIdStore)).toBe("");
  });

  it("is the topmost listed entry, preserving roster order", () => {
    assistantEntriesStore.set([A("first", "listed"), A("second", "listed")]);
    expect(get(defaultAssistantIdStore)).toBe("first");
  });
});
