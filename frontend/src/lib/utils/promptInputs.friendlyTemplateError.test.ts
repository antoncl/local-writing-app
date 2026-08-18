import { describe, expect, it } from "vitest";

import type { PreviewErrorInfo } from "@/lib/aiTypes";
import type { PromptInputDefinition } from "@/lib/types";

import { friendlyTemplateError } from "./promptInputs";

const undef = (name: string, ns?: string): PreviewErrorInfo => ({
  message: `'${name}' is undefined`,
  kind: "undefined",
  undefined_name: name,
  undefined_namespace: ns ?? null,
});

const input = (name: string, extra: Partial<PromptInputDefinition> = {}): PromptInputDefinition => ({
  name,
  type: "text",
  ...extra,
});

describe("friendlyTemplateError", () => {
  // ADR-0060 §7 renamed the input namespace singular→plural with no alias, so
  // every accessor the message suggests must be `inputs.` — echoing the removed
  // `input.` accessor would send the author back into the same error (#1155).
  it("names the plural `inputs.` accessor when listing available inputs", () => {
    const declared = [input("context"), input("genre"), input("lore")];
    const msg = friendlyTemplateError(undef("typo"), declared, {});
    expect(msg).toContain("Available inputs: inputs.context, inputs.genre, inputs.lore.");
    expect(msg).toContain("`inputs.typo`");
    expect(msg).not.toContain("input.");
  });

  it("special-cases the stale singular `input.` migration mistake", () => {
    // A stale `{{ input.context }}` leaves `input` itself undefined, so the
    // undefined name is literally "input" (#1155). Don't prepend `input.` again.
    const msg = friendlyTemplateError(undef("input"), [input("context")], {});
    expect(msg).toBe(
      "The inputs namespace is plural — write `inputs.<name>`, not `input.<name>`.",
    );
  });

  it("does not misfire the migration hint when an input is actually named `input`", () => {
    // Pathological but legal: a declared input literally named "input". The
    // guard is keyed on it being *undeclared*, so this falls through to the
    // normal required/optional handling instead.
    const declared = [input("input", { required: true, label: "Input" })];
    const msg = friendlyTemplateError(undef("input"), declared, { input: "" });
    expect(msg).toContain("required input");
    expect(msg).not.toContain("plural");
  });

  it("suggests the plural accessor in the optional-input guard hint", () => {
    const declared = [input("tone", { required: false })];
    const msg = friendlyTemplateError(undef("tone"), declared, { tone: "" });
    expect(msg).toContain("`inputs.tone`");
    expect(msg).toContain("{% if inputs.tone is defined %}");
    expect(msg).not.toContain("input.tone");
  });

  it("names required inputs by label without an accessor prefix", () => {
    const declared = [input("brief", { required: true, label: "Brief" })];
    const msg = friendlyTemplateError(undef("brief"), declared, { brief: "" });
    expect(msg).toContain("required input `Brief`");
  });

  it("reports a wrong path on a populated namespace (not a missing input)", () => {
    const msg = friendlyTemplateError(undef("language", "project"), [], {});
    expect(msg).toContain("`project.language`");
    expect(msg).toContain("`project.metadata.language`");
  });

  it("passes non-undefined errors through with a hint", () => {
    const err: PreviewErrorInfo = {
      message: "Target scene missing.",
      kind: "scene_not_found",
    };
    expect(friendlyTemplateError(err, [], {})).toContain("Pick a different target scene");
  });
});
