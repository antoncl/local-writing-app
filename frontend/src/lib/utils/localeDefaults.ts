// Locale-derived defaults for a new project's world-canon fields (#1415).
//
// The browser locale is a better default than the two things the schema does
// today — "assume US" (the #317 bug) or "leave blank" — because it is neither:
// a `de-DE` author gets German + metric, an `en-GB` author British spelling, a
// `de-DE`/`fr-FR` author metric. Pure and unit-tested; the create wizard reads
// `navigator.language` and seeds the result into the review-step overrides for
// fields the inherited chain doesn't already state (never clobbering inheritance
// or an author edit). Values are the exact `select` option literals from the
// project schema (default_schema.py).
//
// This is the first place the app reads the browser locale — elsewhere it pins
// English deliberately (relativeTime.ts). That's intentional here: these are the
// author's starting defaults, fully overridable in the wizard, not display text.

// The `language` field's offered ISO-639-1 subtags (default_schema.py `language`).
const LANGUAGES = new Set(["en", "es", "fr", "de", "it", "pt", "nl", "sv", "da", "ja", "zh"]);

// The English-only `spelling` sub-choice, keyed by region subtag.
const SPELLING_BY_REGION: Record<string, string> = {
  GB: "en_GB",
  US: "en_US",
  AU: "en_AU",
  CA: "en_CA",
};

export type LocaleProjectDefaults = {
  language?: string;
  spelling?: string;
  measurement_system: string;
};

// Map a BCP-47 locale (e.g. "en-GB", "de-DE", "pt-BR") to project-field defaults.
// `language`/`spelling` are seeded only when the locale maps to an offered option
// (otherwise left prompted); `measurement_system` is always set — US → US
// customary, everything else → metric — so it is never blank and never US by
// assumption (#317). `imperial` / `in_world` stay a deliberate manual choice.
export function localeProjectDefaults(locale: string): LocaleProjectDefaults {
  const [langRaw = "", regionRaw = ""] = (locale || "").split("-");
  const language = langRaw.toLowerCase();
  const region = regionRaw.toUpperCase();

  const defaults: LocaleProjectDefaults = {
    measurement_system: region === "US" ? "us_customary" : "metric",
  };
  if (LANGUAGES.has(language)) {
    defaults.language = language;
  }
  if (language === "en" && SPELLING_BY_REGION[region]) {
    defaults.spelling = SPELLING_BY_REGION[region];
  }
  return defaults;
}
