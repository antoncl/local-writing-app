import { describe, expect, it } from "vitest";

import {
  addableCloudProviders,
  cloudKeyField,
  configuredCloudProviders,
  eligibleProviders,
} from "@/lib/utils/aiProviders";
import type { ProviderCredentialsView } from "@/lib/types";

const EMPTY: ProviderCredentialsView = {
  anthropic_api_key: "",
  openai_api_key: "",
  openrouter_api_key: "",
  ollama_host: "http://127.0.0.1:11434",
};

describe("configuredCloudProviders", () => {
  it("is empty when no cloud key is set (ollama host does not count)", () => {
    expect(configuredCloudProviders(EMPTY)).toEqual([]);
  });

  it("is empty for null/undefined credentials", () => {
    expect(configuredCloudProviders(null)).toEqual([]);
    expect(configuredCloudProviders(undefined)).toEqual([]);
  });

  it("counts a non-empty key, including the masked placeholder", () => {
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real", openai_api_key: "********" };
    expect(configuredCloudProviders(providers).map((p) => p.id)).toEqual(["anthropic", "openai"]);
  });

  it("treats a whitespace-only key as not configured", () => {
    expect(configuredCloudProviders({ ...EMPTY, openrouter_api_key: "   " })).toEqual([]);
  });
});

describe("addableCloudProviders", () => {
  it("offers every supported cloud provider when none is configured", () => {
    expect(addableCloudProviders(EMPTY).map((p) => p.id)).toEqual([
      "anthropic",
      "openai",
      "openrouter",
    ]);
  });

  it("excludes providers already configured", () => {
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real" };
    expect(addableCloudProviders(providers).map((p) => p.id)).toEqual(["openai", "openrouter"]);
  });
});

describe("eligibleProviders", () => {
  it("is empty under an off policy", () => {
    expect(eligibleProviders("off", EMPTY)).toEqual([]);
  });

  it("is ollama-only under local-only, regardless of credentials", () => {
    expect(eligibleProviders("local-only", EMPTY)).toEqual(["ollama"]);
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real" };
    expect(eligibleProviders("local-only", providers)).toEqual(["ollama"]);
  });

  it("lists configured cloud providers then ollama under cloud-allowed", () => {
    const providers = {
      ...EMPTY,
      anthropic_api_key: "sk-ant-real",
      openrouter_api_key: "sk-or-real",
    };
    expect(eligibleProviders("cloud-allowed", providers)).toEqual([
      "anthropic",
      "openrouter",
      "ollama",
    ]);
  });

  it("falls back to ollama alone under cloud-allowed with no keys set", () => {
    expect(eligibleProviders("cloud-allowed", EMPTY)).toEqual(["ollama"]);
  });
});

describe("cloudKeyField", () => {
  it("maps each cloud provider to its credential field", () => {
    expect(cloudKeyField("anthropic")).toBe("anthropic_api_key");
    expect(cloudKeyField("openrouter")).toBe("openrouter_api_key");
  });

  it("returns null for a non-cloud or unknown provider", () => {
    expect(cloudKeyField("ollama")).toBeNull();
    expect(cloudKeyField("nope")).toBeNull();
  });
});
