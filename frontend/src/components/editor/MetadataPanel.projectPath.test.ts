// @vitest-environment happy-dom
// #417 slice 3: the project's filesystem path moved off the retiring Project
// pane onto the project node's editor, as a read-only `path` computed field in
// the metadata rail. Browser-verify of a live project node is blocked in a
// worktree (out-of-root recents are dimmed, #441), so this mount test is the
// substitute proof that the row actually RENDERS (the #642/#724 lesson: an API
// check that the value is stamped can't see a view-layer that fails to draw it).
// It pins the render contract: given the shipped project:project schema shape, a
// labelled, read-only (lock, no editor) row shows exactly the stamped path.
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

const PROJECT_PATH = "D:\\Users\\anton\\Documents\\local-writer\\universe\\series\\book-2";

// project:project as the backend ships it after this slice — the `path`
// computed field declared on the type, resolved by read_project_node.
const SCHEMA = {
  version: 1,
  entry_types: {
    "project:project": { name: "Project", kind: "project", fields: ["path"] },
  },
  fields: {
    path: { name: "Path", type: "computed", computed: { function: "path" } },
  },
} as unknown as MetadataSchema;

// Set (not reset) per the harness pattern: vitest isolates the store singleton
// per file, and nulling it while the component is still mounted crashes its
// reactive `$metadataSchemaStore` derivation.
beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

describe("MetadataPanel — project path field (#417 slice 3)", () => {
  it("renders the project folder path as a read-only computed row", () => {
    render(MetadataPanel, {
      props: {
        entryType: "project:project",
        status: "",
        metadata: {},
        documentKind: "project",
        documentLabel: "Project",
        documentEntryTypes: [
          ["project:project", SCHEMA.entry_types["project:project"]],
        ] as never,
        metadataFieldIds: ["path"],
        // NodeEditor feeds this from scene.computed_metadata; the row must show
        // exactly what the resolver stamped, verbatim.
        computedFieldString: (id: string) => (id === "path" ? PROJECT_PATH : ""),
      },
    });

    // Labelled, and showing the stamped value.
    expect(screen.getByText("Path")).toBeInTheDocument();
    const value = screen.getByText(PROJECT_PATH);
    expect(value).toBeInTheDocument();
    // Read-only: the computed lock glyph, and no editor control on the row.
    expect(value.querySelector(".ti-lock")).not.toBeNull();
    expect(
      value.closest(".field-row")?.querySelector("input, textarea, select"),
    ).toBeNull();
  });
});
