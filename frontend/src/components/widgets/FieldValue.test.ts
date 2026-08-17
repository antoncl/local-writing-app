// @vitest-environment happy-dom
// FieldValue (#1108, ADR-0064) — the canonical read-only field-value display widget.
// A display widget earns a mount test ([[reference_component_test_harness]]): assert
// each type renders through its widget vocabulary (label, switch, chips, text) — never
// a raw string dump — which is the whole point of unifying field-value display.
import { describe, it, expect } from "vitest";
import { render, screen } from "@/lib/test/component";
import FieldValue from "@/components/widgets/FieldValue.svelte";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

const field = (
  type: MetadataFieldDefinition["type"],
  extra: Partial<MetadataFieldDefinition> = {},
): MetadataFieldDefinition => ({ name: "Field", type, options: [], ...extra }) as MetadataFieldDefinition;

const mount = (f: MetadataFieldDefinition, value: MetadataValue) => render(FieldValue, { props: { field: f, value } });

describe("FieldValue (#1108)", () => {
  it("select: renders the option LABEL, not the raw stored value", () => {
    mount(field("select", { options: [{ value: "alive", label: "Alive" }] }), "alive");
    expect(screen.getByText("Alive")).toBeTruthy();
    expect(screen.queryByText("alive")).toBeNull(); // the raw value never leaks
  });

  it("boolean: renders a switch reflecting the value (never `true`/`false` text)", () => {
    mount(field("boolean"), true);
    expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByText("true")).toBeNull();
  });

  it("tags: renders a chip per tag", () => {
    mount(field("tags"), "hero, villain");
    expect(screen.getByText("hero")).toBeTruthy();
    expect(screen.getByText("villain")).toBeTruthy();
  });

  it("number: renders the value as text", () => {
    mount(field("number"), 42);
    expect(screen.getByText("42")).toBeTruthy();
  });

  it("empty value renders the em-dash placeholder, not a blank or a dump", () => {
    mount(field("long_text"), "");
    expect(screen.getByText("—")).toBeTruthy();
  });
});
