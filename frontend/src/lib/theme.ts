export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "ai-researcher-theme";
export const THEME_CHANGE_EVENT = "ai-researcher-theme-change";

export function readThemePreference(): ThemePreference {
  try {
    const value = window.localStorage?.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

function systemPrefersDark(): boolean {
  try {
    return typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  } catch {
    return false;
  }
}

export function applyThemePreference(preference: ThemePreference): void {
  document.documentElement.dataset.theme = preference === "system"
    ? systemPrefersDark() ? "dark" : "light"
    : preference;
}

export function persistThemePreference(preference: ThemePreference): void {
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Theme persistence is optional; applying it in memory remains safe.
  }
  applyThemePreference(preference);
  window.dispatchEvent(new CustomEvent<ThemePreference>(THEME_CHANGE_EVENT, { detail: preference }));
}
