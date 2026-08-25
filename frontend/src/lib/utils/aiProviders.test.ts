import { describe, expect, it } from "vitest";

import {
  addableProviders,
  configuredProviders,
  eligibleProviders,
  isProviderConfigured,
  providerDescriptor,
  providerField,
  providersForPolicy,
} from "@/lib/utils/aiProviders";
import type { ProviderCredentialsView } from "@/lib/types";

const EMPTY: ProviderCredentialsView = {
  anthropic_api_key: "",
  openai_api_key: "",
  openrouter_api_key: "",
  ollama_host: "http://127.0.0.1:11434",
};

describe("provider descriptors", () => {
  it("models ollama as a url provider with a reachability test, not removable", () => {
    const ollama = providerDescriptor("ollama");
    expect(ollama).toMatchObject({
      field: "ollama_host",
      kind: "url",
      removable: false,
      hasReachabilityTest: true,
    });
  });

  it("models cloud providers as removable secrets with no test", () => {
    const anthropic = providerDescriptor("anthropic");
    expect(anthropic).toMatchObject({
      field: "anthropic_api_key",
      kind: "secret",
      removable: true,
      hasReachabilityTest: false,
    });
  });

  it("maps a provider to its credential field, null for unknown", () => {
    expect(providerField("openrouter")).toBe("openrouter_api_key");
    expect(providerField("ollama")).toBe("ollama_host");
    expect(providerField("nope")).toBeNull();
  });
});

describe("isProviderConfigured", () => {
  it("treats a url provider as always configured (it has a default host)", () => {
    expect(isProviderConfigured(providerDescriptor("ollama")!, EMPTY)).toBe(true);
    expect(isProviderConfigured(providerDescriptor("ollama")!, { ...EMPTY, ollama_host: "" })).toBe(
      true,
    );
  });

  it("treats a secret as configured only when non-empty (masked counts)", () => {
    const desc = providerDescriptor("anthropic")!;
    expect(isProviderConfigured(desc, EMPTY)).toBe(false);
    expect(isProviderConfigured(desc, { ...EMPTY, anthropic_api_key: "   " })).toBe(false);
    expect(isProviderConfigured(desc, { ...EMPTY, anthropic_api_key: "********" })).toBe(true);
  });
});

describe("configuredProviders", () => {
  it("always includes ollama (url), plus any set cloud key", () => {
    expect(configuredProviders(EMPTY).map((p) => p.id)).toEqual(["ollama"]);
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real", openai_api_key: "********" };
    expect(configuredProviders(providers).map((p) => p.id)).toEqual([
      "anthropic",
      "openai",
      "ollama",
    ]);
  });

  it("honours the allowed scope", () => {
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real" };
    // local-only scope shows only ollama, even with a cloud key set
    expect(configuredProviders(providers, ["ollama"]).map((p) => p.id)).toEqual(["ollama"]);
  });

  it("is empty for an empty scope (policy off)", () => {
    expect(configuredProviders(EMPTY, [])).toEqual([]);
  });
});

describe("addableProviders", () => {
  it("offers unconfigured cloud providers, never ollama (always configured)", () => {
    expect(addableProviders(EMPTY).map((p) => p.id)).toEqual([
      "anthropic",
      "openai",
      "openrouter",
    ]);
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real" };
    expect(addableProviders(providers).map((p) => p.id)).toEqual(["openai", "openrouter"]);
  });

  it("offers nothing addable under a local-only (ollama) scope", () => {
    expect(addableProviders(EMPTY, ["ollama"])).toEqual([]);
  });
});

describe("providersForPolicy — the slider just widens the set", () => {
  it("off allows none", () => {
    expect(providersForPolicy("off")).toEqual([]);
  });

  it("local-only allows ollama only", () => {
    expect(providersForPolicy("local-only")).toEqual(["ollama"]);
  });

  it("cloud-allowed allows every provider (cloud keys plus ollama)", () => {
    expect(providersForPolicy("cloud-allowed")).toEqual([
      "anthropic",
      "openai",
      "openrouter",
      "ollama",
    ]);
  });
});

describe("eligibleProviders (send-path/picker scope — unchanged)", () => {
  it("is empty under an off policy", () => {
    expect(eligibleProviders("off", EMPTY)).toEqual([]);
  });

  it("is ollama-only under local-only, regardless of credentials", () => {
    expect(eligibleProviders("local-only", EMPTY)).toEqual(["ollama"]);
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real" };
    expect(eligibleProviders("local-only", providers)).toEqual(["ollama"]);
  });

  it("lists configured cloud providers then ollama under cloud-allowed", () => {
    const providers = { ...EMPTY, anthropic_api_key: "sk-ant-real", openrouter_api_key: "sk-or-real" };
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
