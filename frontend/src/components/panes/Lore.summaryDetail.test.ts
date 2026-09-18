// @vitest-environment happy-dom
// Lore row detail line (#2008): entryDetailText renders the entry type's
// nominated (or synthesized) summary fields' present values. Modeled on
// Lore.test.ts's mount harness (#642).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import Lore from "./Lore.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes } from "@/lib/stores/tagNodes";
import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore" },
    "lore:character": {
      name: "Character",
      kind: "lore",
      parent: "lore:base",
      fields: ["role", "age"],
      // Explicit nomination (#2008) — role first, then age.
      summary_fields: ["role", "age"],
    },
  },
  fields: {
    role: {
      name: "Role",
      type: "select",
      options: [{ value: "captain", label: "Captain" }, { value: "ranger", label: "Ranger" }],
    },
    age: { name: "Age", type: "number" },
  },
} as unknown as MetadataSchema;

function entry(id: string, title: string, metadata: LoreEntrySummary["metadata"]): LoreEntrySummary {
  return { id, title, body: "", entry_type: "lore:character", metadata };
}

const noop = () => {};

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
  clearTagNodes();
});

describe("Lore pane — row detail line from nominated summary fields (#2008)", () => {
  it("renders the nominated fields' present values, joined with ·", () => {
    render(Lore, {
      props: {
        entries: [entry("l-a", "Boromir", { role: "captain", age: 25 })],
        viewSpec: defaultView("lore", SCHEMA),
        onOpenEntry: noop,
      },
    });
    expect(screen.getByText("Boromir")).toBeInTheDocument();
    expect(screen.getByText("Captain · 25")).toBeInTheDocument();
  });

  it("skips a nominated field the entry leaves empty", () => {
    render(Lore, {
      props: {
        entries: [entry("l-b", "Faramir", { role: "ranger" })],
        viewSpec: defaultView("lore", SCHEMA),
        onOpenEntry: noop,
      },
    });
    expect(screen.getByText("Faramir")).toBeInTheDocument();
    expect(screen.getByText("Ranger")).toBeInTheDocument();
  });

  it("renders no detail line when nothing is present", () => {
    render(Lore, {
      props: {
        entries: [entry("l-c", "Gollum", {})],
        viewSpec: defaultView("lore", SCHEMA),
        onOpenEntry: noop,
      },
    });
    const row = screen.getByText("Gollum").closest(".node-row-text");
    expect(row?.querySelector("small")).toBeNull();
  });
});
