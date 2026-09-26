import { describe, expect, it } from "vitest";
import { adoptSavedItemIds, withStampedBeatIds } from "./beatRoster";
import type { EntryMetadata } from "@/lib/metadataTypes";

describe("withStampedBeatIds", () => {
  it("fills a missing id positionally from the saved roster", () => {
    const current = [{ title: "Setup" }];
    const saved = [{ title: "Setup", id: "b1" }];
    expect(withStampedBeatIds(current, saved)).toEqual([{ title: "Setup", id: "b1" }]);
  });

  it("keeps an existing id untouched", () => {
    const current = [{ title: "Setup", id: "existing" }];
    const saved = [{ title: "Setup", id: "b1" }];
    expect(withStampedBeatIds(current, saved)).toBeNull();
  });

  it("returns null when every item already has an id", () => {
    const current = [{ title: "A", id: "a" }, { title: "B", id: "b" }];
    const saved = [{ title: "A", id: "a" }, { title: "B", id: "b" }];
    expect(withStampedBeatIds(current, saved)).toBeNull();
  });

  it("returns null when either argument is not an array", () => {
    expect(withStampedBeatIds(null, [{ title: "A" }])).toBeNull();
    expect(withStampedBeatIds([{ title: "A" }], null)).toBeNull();
    expect(withStampedBeatIds("not an array", "also not")).toBeNull();
  });

  it("leaves the tail untouched when saved is shorter than current", () => {
    const current = [{ title: "A" }, { title: "B" }];
    const saved = [{ title: "A", id: "a" }];
    expect(withStampedBeatIds(current, saved)).toEqual([{ title: "A", id: "a" }, { title: "B" }]);
  });
});

describe("adoptSavedItemIds (#2255, generalised by ADR-0096 §1/§2)", () => {
  const BEAT_IDENTITY = { beats: "id", instance_beats: "id" };

  it("takes the minted id for a new beat, id last like the backend", () => {
    const draft: EntryMetadata = { color: "red", instance_beats: [{ title: "A", id: "a" }, { title: "New" }] };
    const saved = { color: "red", instance_beats: [{ title: "A", id: "a" }, { title: "New", id: "beat_1" }] };
    const next = adoptSavedItemIds(draft, draft, saved, BEAT_IDENTITY);
    expect(next).toEqual(saved);
    // The pane's dirty check is a JSON.stringify compare — key order matters.
    expect(JSON.stringify(next)).toBe(JSON.stringify(saved));
  });

  it("takes the re-salted id for a duplicated beat", () => {
    const draft = { beats: [{ title: "A", id: "a" }, { title: "A", id: "a" }] };
    const saved = { beats: [{ title: "A", id: "a" }, { title: "A", id: "beat_2" }] };
    expect(adoptSavedItemIds(draft, draft, saved, BEAT_IDENTITY)).toEqual(saved);
  });

  it("leaves a roster edited while the save was in flight for the next save", () => {
    const sent = { instance_beats: [{ title: "New" }] };
    const draft = { instance_beats: [{ title: "Newer" }] };
    const saved = { instance_beats: [{ title: "New", id: "beat_1" }] };
    expect(adoptSavedItemIds(draft, sent, saved, BEAT_IDENTITY)).toBeNull();
  });

  it("returns null when every id already matches, or there is no beat list", () => {
    const draft = { instance_beats: [{ title: "A", id: "a" }] };
    expect(adoptSavedItemIds(draft, draft, draft, BEAT_IDENTITY)).toBeNull();
    expect(adoptSavedItemIds({ rank: "x" }, { rank: "x" }, { rank: "x" }, BEAT_IDENTITY)).toBeNull();
  });

  it("uses a non-`id` identity key when the schema declares one", () => {
    const draft = { rumours: [{ text: "Old", slug: "old" }, { text: "New", slug: null }] };
    const saved = { rumours: [{ text: "Old", slug: "old" }, { text: "New", slug: "rumour_1" }] };
    expect(adoptSavedItemIds(draft, draft, saved, { rumours: "slug" })).toEqual(saved);
  });
});
