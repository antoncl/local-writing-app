// Theme preference: "system" follows prefers-color-scheme; "light" /
// "dark" override. Persisted in localStorage and reflected on
// document.documentElement[data-theme]. A small init script in
// index.html applies the saved preference before Svelte mounts so the
// page doesn't flash light during boot.

import { writable, type Writable } from "svelte/store";

export type ThemePreference = "system" | "light" | "dark";
export type EffectiveTheme = "light" | "dark";

const STORAGE_KEY = "themePreference";
const VALID: ThemePreference[] = ["system", "light", "dark"];

export const themePreference: Writable<ThemePreference> = writable(loadPreference());

function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (VALID as string[]).includes(value);
}

export function loadPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (isThemePreference(raw)) return raw;
  } catch {
    // localStorage unavailable (private mode quirks etc.) — fall through.
  }
  return "system";
}

export function savePreference(pref: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    // Silent — preference is best-effort.
  }
}

export function resolveEffectiveTheme(pref: ThemePreference): EffectiveTheme {
  if (pref === "light" || pref === "dark") return pref;
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "light";
}

export function applyTheme(pref: ThemePreference): void {
  const effective = resolveEffectiveTheme(pref);
  document.documentElement.setAttribute("data-theme", effective);
}

// Cycle order matches what the toggle button steps through: system →
// light → dark → system. Single-button affordance, three states.
export function nextPreference(current: ThemePreference): ThemePreference {
  if (current === "system") return "light";
  if (current === "light") return "dark";
  return "system";
}

// Wire the preference store to the DOM + system theme changes. Call
// once from App.svelte on mount. Returns a cleanup function.
export function installThemeWiring(): () => void {
  const unsubscribe = themePreference.subscribe((pref) => {
    savePreference(pref);
    applyTheme(pref);
  });

  let mediaCleanup = () => {};
  if (typeof window !== "undefined" && window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      // Re-apply only when following the system — explicit light/dark
      // shouldn't react to OS toggles.
      themePreference.update((current) => {
        if (current === "system") applyTheme(current);
        return current;
      });
    };
    mq.addEventListener("change", onChange);
    mediaCleanup = () => mq.removeEventListener("change", onChange);
  }

  return () => {
    unsubscribe();
    mediaCleanup();
  };
}
