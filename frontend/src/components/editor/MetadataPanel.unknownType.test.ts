// @vitest-environment happy-dom
// #87: an entry_type stored on a node but absent from the resolved schema (an
// out-of-band edit, a stale import, or a machine file predating a schema re-key)
// used to render silently as another type's fields. The type header now shows a
// visible warning so the fallback stops being invisible. Browser-verify of a
// live node is blocked in a worktree (#441), so this mount test is the render
// proof — the #642/#724 lesson that a value stamped in state is worthless if the
// view never draws it.
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:note": { name: "Note", kind: "lore", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

// documentKind "lore" avoids the assistant ProviderTierPicker, which would
// fetch /api/ai/providers on mount (the #973 network guard). The warning
// condition is documentKind-independent — it turns on the resolved schema alone.
function mount(entryType: string) {
  render(MetadataPanel, {
    props: {
      entryType,
      status: "",
      metadata: {},
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [
        ["lore:note", SCHEMA.entry_types["lore:note"]],
      ] as never,
      metadataFieldIds: [],
    },
  });
}

describe("MetadataPanel — unknown entry_type warning (#87)", () => {
  it("warns when the stored type is not in the schema, naming the value", () => {
    // A bare `assistant` (the motivating case: a machine file predating the
    // `assistant:assistant` re-key) is unresolved against this schema.
    mount("assistant");
    const warning = document.querySelector(".rail-type-warning");
    expect(warning).not.toBeNull();
    expect(warning?.textContent).toContain("Unknown type");
    // The offending value is surfaced verbatim so the author can act on it.
    expect(warning?.querySelector("code")?.textContent).toBe("assistant");
  });

  it("stays silent when the stored type resolves in the schema", () => {
    mount("lore:note");
    expect(document.querySelector(".rail-type-warning")).toBeNull();
  });
});
