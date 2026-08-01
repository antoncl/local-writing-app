// Template-instances store (ADR-0048 S7 Slice 5a) — the arc palette's roster.
// Pure logic, node env.
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import {
  templateInstancesStore,
  refreshTemplateInstances,
  setTemplateInstances,
  deleteTemplateInstance,
  clearTemplateInstances,
} from "./templateInstances";
import type { TemplateInstanceSummary } from "@/lib/types";

const arc = (id: string, title: string): TemplateInstanceSummary => ({
  id,
  title,
  body: "",
  entry_type: "plot:template_instance",
  metadata: {},
});

afterEach(() => {
  clearTemplateInstances();
  vi.restoreAllMocks();
});

describe("refreshTemplateInstances", () => {
  it("fetches the instance roster into the store", async () => {
    const spy = vi
      .spyOn(api, "listTemplateInstances")
      .mockResolvedValue({ entries: [arc("i1", "Hero's Journey")] });
    await refreshTemplateInstances();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(get(templateInstancesStore).map((a) => a.title)).toEqual(["Hero's Journey"]);
  });
});

describe("setTemplateInstances", () => {
  it("write-through mirrors a roster without a fetch", () => {
    setTemplateInstances([arc("i1", "Arc")]);
    expect(get(templateInstancesStore)).toHaveLength(1);
  });
});

describe("deleteTemplateInstance", () => {
  it("deletes and mirrors the refreshed roster the endpoint returns", async () => {
    setTemplateInstances([arc("i1", "Keep"), arc("i2", "Drop")]);
    const spy = vi
      .spyOn(api, "deleteTemplateInstance")
      .mockResolvedValue({ entries: [arc("i1", "Keep")] });
    await deleteTemplateInstance("i2");
    expect(spy).toHaveBeenCalledWith("i2");
    expect(get(templateInstancesStore).map((a) => a.id)).toEqual(["i1"]);
  });
});

describe("clearTemplateInstances", () => {
  it("empties the store", () => {
    setTemplateInstances([arc("i1", "Arc")]);
    clearTemplateInstances();
    expect(get(templateInstancesStore)).toEqual([]);
  });
});
