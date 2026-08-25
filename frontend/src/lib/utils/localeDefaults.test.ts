import { describe, it, expect } from "vitest";
import { localeProjectDefaults } from "@/lib/utils/localeDefaults";

describe("localeProjectDefaults (#1415)", () => {
  it("maps a German locale to German + metric, no spelling", () => {
    expect(localeProjectDefaults("de-DE")).toEqual({
      measurement_system: "metric",
      language: "de",
    });
  });

  it("maps British English to en + British spelling + metric", () => {
    expect(localeProjectDefaults("en-GB")).toEqual({
      measurement_system: "metric",
      language: "en",
      spelling: "en_GB",
    });
  });

  it("maps American English to en + American spelling + US customary", () => {
    expect(localeProjectDefaults("en-US")).toEqual({
      measurement_system: "us_customary",
      language: "en",
      spelling: "en_US",
    });
  });

  it("maps the other English regions with an option", () => {
    expect(localeProjectDefaults("en-AU").spelling).toBe("en_AU");
    expect(localeProjectDefaults("en-CA").spelling).toBe("en_CA");
    // AU/CA are not the US, so metric.
    expect(localeProjectDefaults("en-AU").measurement_system).toBe("metric");
  });

  it("seeds no spelling for an English region without an option", () => {
    const d = localeProjectDefaults("en-IE");
    expect(d.language).toBe("en");
    expect(d.spelling).toBeUndefined();
    expect(d.measurement_system).toBe("metric");
  });

  it("seeds no spelling for a non-English language", () => {
    expect(localeProjectDefaults("pt-BR")).toEqual({
      measurement_system: "metric",
      language: "pt",
    });
  });

  it("leaves language unset when the locale's language isn't offered", () => {
    // Polish is not in the schema's language options → no language, no spelling.
    expect(localeProjectDefaults("pl-PL")).toEqual({ measurement_system: "metric" });
  });

  it("is case-insensitive and tolerates a bare language / empty locale", () => {
    expect(localeProjectDefaults("EN-gb")).toEqual({
      measurement_system: "metric",
      language: "en",
      spelling: "en_GB",
    });
    expect(localeProjectDefaults("de")).toEqual({ measurement_system: "metric", language: "de" });
    // Empty/unknown → the safe metric default only (never blank, never US).
    expect(localeProjectDefaults("")).toEqual({ measurement_system: "metric" });
  });
});
