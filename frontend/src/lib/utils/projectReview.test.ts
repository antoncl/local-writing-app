import { describe, expect, it } from "vitest";

import type { MetadataSchema } from "@/lib/types";
import { PROJECT_ENTRY_TYPE, projectReviewRows, resetTargetLabel } from "@/lib/utils/projectReview";

// A minimal project schema: one prompted select (pov_mode), one inheritable
// select (measurement_system), an intrinsic field and a computed field that must
// both be filtered out.
const SCHEMA: MetadataSchema = {
  version: 1,
  entry_types: {
    [PROJECT_ENTRY_TYPE]: {
      name: "Project",
      kind: "project",
      fields: ["title", "measurement_system", "pov_mode", "tense", "project_cost"],
    },
  },
  fields: {
    title: { name: "Title", type: "text", options: [], intrinsic: true },
    measurement_system: {
      name: "Measurement system",
      type: "select",
      options: [
        { value: "metric", label: "Metric" },
        { value: "imperial", label: "Imperial" },
      ],
    },
    pov_mode: {
      name: "Point of view",
      type: "select",
      options: [{ value: "first", label: "First person" }],
    },
    tense: { name: "Tense", type: "select", options: [], default: "past" },
    project_cost: { name: "Cost", type: "computed", options: [], category: "computed" },
  },
};

describe("projectReviewRows", () => {
  it("skips intrinsic and computed fields", () => {
    const ids = projectReviewRows(SCHEMA, {}, {}, {}).map((r) => r.fieldId);
    expect(ids).not.toContain("title"); // intrinsic
    expect(ids).not.toContain("project_cost"); // computed
    expect(ids).toEqual(["measurement_system", "pov_mode", "tense"]);
  });

  it("marks an ancestor-supplied value as inherited and names the source", () => {
    const rows = projectReviewRows(
      SCHEMA,
      { measurement_system: "metric" },
      { measurement_system: "Honorverse" },
      {},
    );
    const row = rows.find((r) => r.fieldId === "measurement_system")!;
    expect(row.provenance).toBe("inherited");
    expect(row.value).toBe("metric");
    expect(row.sourceLabel).toBe("Honorverse");
    expect(row.clearable).toBe(false);
  });

  it("falls to the schema default when no ancestor states the field", () => {
    const row = projectReviewRows(SCHEMA, {}, {}, {}).find((r) => r.fieldId === "tense")!;
    expect(row.provenance).toBe("default");
    expect(row.value).toBe("past");
    expect(row.sourceLabel).toBeNull();
  });

  it("shows an unstated field as a default with a null value, not inherited", () => {
    const row = projectReviewRows(SCHEMA, {}, {}, {}).find((r) => r.fieldId === "pov_mode")!;
    expect(row.provenance).toBe("default");
    expect(row.value).toBeNull();
  });

  it("treats an ancestor's explicitly-empty value as inherited, not default", () => {
    // The ancestor states the key (present in `inherited`/`sources`) with an
    // empty value. The runtime channel resolves it to that empty value, so the
    // review must read it as inherited — showing the field's default here would
    // make the preview disagree with what the project actually resolves.
    const rows = projectReviewRows(SCHEMA, { tense: "" }, { tense: "Honorverse" }, {});
    const row = rows.find((r) => r.fieldId === "tense")!;
    expect(row.provenance).toBe("inherited");
    expect(row.value).toBe(""); // the inherited empty value, NOT the "past" default
    expect(row.sourceLabel).toBe("Honorverse");
  });

  it("treats a locally-set field as a live override, keeping its reset source", () => {
    // The author overrides an inherited value: it reads live and clearable, and
    // still remembers the ancestor it would reset to.
    const row = projectReviewRows(
      SCHEMA,
      { measurement_system: "metric" },
      { measurement_system: "Honorverse" },
      { measurement_system: "imperial" },
    ).find((r) => r.fieldId === "measurement_system")!;
    expect(row.provenance).toBe("local");
    expect(row.value).toBe("imperial");
    expect(row.clearable).toBe(true);
    expect(row.sourceLabel).toBe("Honorverse");
    expect(resetTargetLabel(row)).toBe("Honorverse");
  });

  it("resets a locally-set default field back to 'default'", () => {
    const row = projectReviewRows(SCHEMA, {}, {}, { pov_mode: "first" }).find(
      (r) => r.fieldId === "pov_mode",
    )!;
    expect(row.provenance).toBe("local");
    expect(row.clearable).toBe(true);
    expect(resetTargetLabel(row)).toBe("default");
  });

  it("honours an explicit local value even when it equals the inherited one", () => {
    // Setting a field equal to its inherited value still authors it locally —
    // the pop-key model treats presence, not equality, as the signal.
    const row = projectReviewRows(
      SCHEMA,
      { measurement_system: "metric" },
      { measurement_system: "Honorverse" },
      { measurement_system: "metric" },
    ).find((r) => r.fieldId === "measurement_system")!;
    expect(row.provenance).toBe("local");
    expect(row.clearable).toBe(true);
  });

  it("returns nothing when the project entry type is absent", () => {
    const empty: MetadataSchema = { version: 1, entry_types: {}, fields: {} };
    expect(projectReviewRows(empty, {}, {}, {})).toEqual([]);
  });
});
