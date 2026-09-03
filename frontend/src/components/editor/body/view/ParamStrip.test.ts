// @vitest-environment happy-dom
// ADR-0082 §2 round 2 (P5): create_missing is offered ONLY where the metadata
// panel is the host — a `createLayerId` is passed there and nowhere else. The
// assistant default view's TAG parameter resolves to the real `assistant_tags`
// field (create_missing: true), so ParamStrip is the concrete regression this
// pins: it renders that field through FieldValueEditor with no `createLayerId`
// prop at all, so no "Create ‹x›" row can ever reach a filter strip.
import { describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import ParamStrip from "./ParamStrip.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema, ViewSpec } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "assistant:assistant": { name: "Assistant", kind: "assistant" },
    "tag:assistant_tag": { name: "Assistant tag", kind: "tag" },
  },
  fields: {
    assistant_tags: {
      name: "Preferred assistant tags",
      type: "entity_ref_list",
      options: [],
      picker_config: {
        sources: [{ kind: "tag", expr: { type: "tag:assistant_tag" } }],
        create_missing: true,
      },
    },
  },
} as unknown as MetadataSchema;

// Mirrors the shipped assistant default view's TAG param (evaluateView.ts /
// views.py) — a `field` predicate on `assistant_tags`, not a `tagged:` leaf.
const ASSISTANT_TAG_SPEC: ViewSpec = {
  kind: "assistant",
  expr: {
    filter: {
      of: { type: "assistant:assistant" },
      pred: { field: { key: "assistant_tags", op: "overlap", value: { var: "TAG" } } },
    },
  },
  params: [{ name: "TAG", label: "Tag", default: null }],
};

describe("ParamStrip — the assistant view's TAG filter offers no create (P5)", () => {
  it("shows no create row for an unmatched name — no createLayerId reaches ReferencePicker here", async () => {
    metadataSchemaStore.set(SCHEMA);
    render(ParamStrip, { props: { spec: ASSISTANT_TAG_SPEC, schema: SCHEMA } });

    await fireEvent.click(screen.getByRole("button", { name: "Add Tag" }));
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: "Editor" } });
    await tick();

    expect(screen.queryByTestId("node-picker-create")).toBeNull();
    metadataSchemaStore.set(null as unknown as MetadataSchema);
  });
});
