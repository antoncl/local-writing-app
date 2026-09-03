// @vitest-environment happy-dom
// #1797 — a tag-vocabulary `entity_ref_list` flip (ADR-0082 §2) is now
// reviewable (entryProposal.svelte.ts's `structuredFlips`). The validator only
// resolves a title matching an EXISTING tag; an unmatched one rides through
// as a plain string (never minted at validation — see the module note in
// `entryProposal.svelte.ts`), so the candidate side can MIX resolved ids with
// unresolved titles. The candidate side itself (known-title chip vs "new tag"
// pill) is `TagFlipChips`' own render, covered by `TagFlipChips.test.ts`
// (round 2, Y7) — this file keeps only what's genuinely MetadataPanel-level:
// that the strip is the widget USED for a tag-vocabulary flip, and the
// "Current:" hint (MetadataPanel's own `flipCurrentHint`), which must resolve
// ids to titles the same way the candidate side does.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import type { MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:note": { name: "Note", kind: "lore", fields: ["tags"] },
    // `createTargetFor`/`singleConcreteTarget` resolve the picker_config's
    // target entry_type against the schema — must be present for
    // `isTagFlipField` to recognise `tags` as the tag-vocabulary carve-out.
    "tag:tag": { name: "Tag", kind: "tag" },
  },
  fields: {
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: {
        create_missing: true,
        sources: [{ kind: "tag", expr: { type: "tag:tag" } }],
      },
    },
  },
} as unknown as MetadataSchema;

const OLD: TagEntry = { id: "tag_old", title: "Old Tag", entry_type: "tag:tag", metadata: {} };
const NEW: TagEntry = { id: "tag_new", title: "New Tag", entry_type: "tag:tag", metadata: {} };

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  tagNodesStore.set([OLD, NEW]);
});

function mount(was: string[]) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:note",
      status: "",
      metadata: { tags: [OLD.id] },
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:note", SCHEMA.entry_types["lore:note"]]] as never,
      metadataFieldIds: ["tags"],
      compare: {
        fields: { tags: { was, now: [OLD.id] } },
        side: "was",
        resolve: { adopted: () => false, onToggle: vi.fn() },
      },
      onMetadataChange: vi.fn(),
    },
  });
}

describe("MetadataPanel — tag-vocabulary flip resolves both sides to titles (#1797)", () => {
  it('shows "Current: Old Tag", not the raw id', () => {
    mount([NEW.id]);
    expect(screen.getByText("Current: Old Tag")).toBeTruthy();
  });

  it("renders the tag-vocabulary flip through TagFlipChips (a known chip and a new-tag pill)", () => {
    mount([NEW.id, "Brand New Tag"]);
    // Both testids are TagFlipChips' own — their presence pins that
    // MetadataPanel routed this flip to the chip strip, not FieldValueEditor.
    expect(screen.getByTestId("flip-tag-chip").textContent).toBe("New Tag");
    expect(screen.getByTestId("flip-new-tag")).toBeTruthy();
  });
});
