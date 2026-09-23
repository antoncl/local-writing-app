// @vitest-environment happy-dom
// ADR-0091 §2/§7 — the Propagate pane's diff column: the rule line's exact
// strings for each of §2's three states, the nothing-changed sentence (with
// its deliberate captured-time exception), and reference values rendering as
// titles (#2133) — including two same-titled tag ids staying two distinct
// pills.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@/lib/test/component";
import PropagateDiff from "./PropagateDiff.svelte";
import { api } from "@/lib/api";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { loreEntriesStore } from "@/lib/stores/lore";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import type { ChangeCandidateSet, LoreEntry, MetadataSchema, Snapshot, SnapshotDetail } from "@/lib/types";

const SCHEMA: MetadataSchema = {
  version: 1,
  entry_types: {},
  fields: {
    rank: { name: "Rank", type: "text", options: [] },
    aliases: { name: "Aliases", type: "list", options: [], item_type: "text" },
    captain: { name: "Captain", type: "entity_ref", options: [] },
    tags: { name: "Tags", type: "entity_ref_list", options: [] },
  },
};

const liveEntry: LoreEntry = {
  id: "lore_marek",
  title: "Marek Vell",
  body: "…",
  revision: "3",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
};

function baseline(overrides: Partial<SnapshotDetail> = {}): SnapshotDetail {
  return {
    snapshot: {
      id: "snap_1",
      snapshot_of: "lore_marek",
      captured_at: "2026-09-01T12:00:00.000000+00:00",
      content_written_at: "2020-01-01T00:00:00.000000+00:00", // deliberately stale
      retention: "kept",
      description: "",
      origin: "propagation",
      schema_version: 1,
    },
    title: "Marek Vell",
    status: "",
    metadata: {},
    body: "…",
    ...overrides,
  };
}

function snapshotList(): Snapshot[] {
  return [baseline().snapshot];
}

function candidateSet(overrides: Partial<ChangeCandidateSet>): ChangeCandidateSet {
  return {
    source_id: "lore_marek",
    baseline_snapshot_id: "snap_1",
    changed_fields: [],
    body_changed: false,
    whole_entry: false,
    items: [],
    ...overrides,
  };
}

describe("PropagateDiff — the rule line (ADR-0091 §2)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baseline());
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);
  });

  it("body-only reads the declared+markers+mentions sentence", async () => {
    render(PropagateDiff, {
      sourceId: "lore_marek",
      sourceTitle: "Marek Vell",
      candidates: candidateSet({ body_changed: true }),
      snapshots: snapshotList(),
    });
    expect(
      await screen.findByText(
        "The body changed: entries it names and that name it start kept, with the declared rows and the markers.",
      ),
    ).toBeInTheDocument();
  });

  it("fields-only reads the declared+markers-kept, mentions-folded sentence", async () => {
    render(PropagateDiff, {
      sourceId: "lore_marek",
      sourceTitle: "Marek Vell",
      candidates: candidateSet({ changed_fields: ["rank", "aliases"] }),
      snapshots: snapshotList(),
    });
    expect(
      await screen.findByText("Fields changed (rank, aliases): declared rows and markers start kept; mentions are folded."),
    ).toBeInTheDocument();
  });
});

describe("PropagateDiff — the nothing-changed state (ADR-0091 §2/§7)", () => {
  it("reads the pick-an-earlier-snapshot sentence, aged by CAPTURE time (not content time)", async () => {
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baseline());
    vi.spyOn(api, "getLoreEntry").mockResolvedValue(liveEntry);

    render(PropagateDiff, {
      sourceId: "lore_marek",
      sourceTitle: "Marek Vell",
      candidates: candidateSet({}), // nothing changed
      snapshots: snapshotList(),
    });

    // captured_at is 2026-09-01, content_written_at is 2020 — the sentence
    // must be aged off the FORMER (a deliberate exception to notchWhen).
    const sentence = await screen.findByText(/Nothing has changed since the last propagation/);
    expect(sentence.textContent).toContain("pick an earlier snapshot to propagate an older change");
    expect(sentence.textContent).not.toMatch(/2020|years? ago/);
  });
});

describe("PropagateDiff — reference values render as titles, never as ids (#2133)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    metadataSchemaStore.set(SCHEMA);
    loreEntriesStore.set([
      { id: "lore_guard", title: "City Guard", body: "", entry_type: "lore:base", metadata: {} },
    ]);
  });

  it("a single entity_ref field's value resolves to its title", async () => {
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baseline({ metadata: { captain: "lore_unknown" } }));
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...liveEntry, metadata: { captain: "lore_guard" } });

    render(PropagateDiff, {
      sourceId: "lore_marek",
      sourceTitle: "Marek Vell",
      candidates: candidateSet({ changed_fields: ["captain"] }),
      snapshots: snapshotList(),
    });

    expect(await screen.findByText("City Guard")).toBeInTheDocument();
    // The unresolved OLD value renders as its bare id (no roster knows it).
    expect(screen.getByText("lore_unknown")).toBeInTheDocument();
  });

  it("two tag ids sharing a title still render as two distinct pills", async () => {
    tagNodesStore.set([
      { id: "tag_a", title: "Hope", entry_type: "tag:tag", metadata: {} },
      { id: "tag_b", title: "Hope", entry_type: "tag:tag", metadata: {} },
    ]);
    vi.spyOn(api, "readNodeSnapshot").mockResolvedValue(baseline({ metadata: { tags: ["tag_a"] } }));
    vi.spyOn(api, "getLoreEntry").mockResolvedValue({ ...liveEntry, metadata: { tags: ["tag_a", "tag_b"] } });

    render(PropagateDiff, {
      sourceId: "lore_marek",
      sourceTitle: "Marek Vell",
      candidates: candidateSet({ changed_fields: ["tags"] }),
      snapshots: snapshotList(),
    });

    const pills = await screen.findAllByText("Hope");
    expect(pills).toHaveLength(2);
    // One is the kept id (tag_a, "same"), the other newly added (tag_b, "now").
    expect(pills.some((el) => el.className.includes("same"))).toBe(true);
    expect(pills.some((el) => el.className.includes("pill-now"))).toBe(true);
  });
});
