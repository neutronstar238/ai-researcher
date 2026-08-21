import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const tokensCss = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");
const globalCss = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

const REQUIRED_TOKENS = [
  "--color-heading",
  "--color-control-text",
  "--color-control-surface",
  "--color-surface-muted",
  "--color-text-muted",
  "--color-divider",
  "--color-hover",
  "--color-focus",
  "--color-on-action",
  "--color-on-brand",
  "--color-danger-text",
] as const;

test.each([":root", ':root[data-theme="dark"]'])("%s defines complete semantic theme tokens with accessible contrast", (selector) => {
  const tokens = tokenBlock(selector);
  const color = (name: string) => requiredToken(tokens, name);
  for (const name of REQUIRED_TOKENS) expect(color(name)).toMatch(/^#[0-9a-f]{6}$/i);

  expect(contrast(color("--color-heading"), color("--color-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-text"), color("--color-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-text-muted"), color("--color-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-control-text"), color("--color-control-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-action"), color("--color-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-danger"), color("--color-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-on-action"), color("--color-action"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-on-brand"), color("--color-brand"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-success-text"), color("--color-success-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-action-text"), color("--color-action-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-danger-text"), color("--color-danger-surface"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("--color-focus"), color("--color-page"))).toBeGreaterThanOrEqual(3);
});

test("core navigation, headings, controls, facts, tables, toast, hover, badges, and focus consume semantic tokens", () => {
  expect(rule("button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible")).toContain("outline: 3px solid var(--color-focus)");
  expect(rule(".nav-link")).toContain("color: var(--color-nav-text)");
  expect(rule(".nav-link:hover")).toContain("background: var(--color-nav-hover)");
  expect(rule(".app-header")).toContain("background: var(--color-header-surface)");
  expect(rule(".feature-heading h1")).toContain("color: var(--color-heading)");
  expect(rule(".feature-card > h2")).toContain("color: var(--color-heading)");
  expect(rule(".button-secondary")).toContain("background: var(--color-control-surface)");
  expect(rule(".button-secondary")).toContain("color: var(--color-control-text)");
  expect(rule(".search-field input, .status-filter select, .form-field input, .form-field textarea")).toContain("background: var(--color-control-surface)");
  expect(rule(".run-detail-facts")).toContain("background: var(--color-surface-muted)");
  expect(rule(".dashboard-table th, .dashboard-table td")).toContain("border-bottom: 1px solid var(--color-divider)");
  expect(rule(".projects-table th, .projects-table td")).toContain("border-bottom: 1px solid var(--color-divider)");
  expect(rule(".toast")).toContain("background: var(--color-control-surface)");
  expect(rule(".status-badge")).toContain("background: var(--color-surface-muted)");
});

test("light navigation preserves the screenshot foreground and hover pixels through dedicated tokens", () => {
  const light = tokenBlock(":root");

  expect(requiredToken(light, "--color-nav-text")).toBe("#26354f");
  expect(requiredToken(light, "--color-nav-hover")).toBe("rgb(11 59 130 / 7%)");
  expect(rule(".nav-link")).toContain("color: var(--color-nav-text)");
  expect(rule(".nav-link:hover")).toContain("background: var(--color-nav-hover)");
});

test("dark inactive navigation keeps normal-text contrast against the sidebar", () => {
  const dark = tokenBlock(':root[data-theme="dark"]');

  expect(contrast(requiredToken(dark, "--color-nav-text"), requiredToken(dark, "--color-sidebar"))).toBeGreaterThanOrEqual(4.5);
  expect(requiredToken(dark, "--color-nav-hover")).toMatch(/^#[0-9a-f]{6}$/i);
});

function tokenBlock(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const body = tokensCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+)\s*;/gi)].map((match) => [match[1], match[2]?.trim()]));
}

function requiredToken(tokens: Record<string, string>, name: string): string {
  const value = tokens[name];
  if (value === undefined) throw new Error(`Missing theme token: ${name}`);
  return value;
}

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return globalCss.match(new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`))?.[1]?.replace(/\s+/g, " ").trim() ?? "";
}

function contrast(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((start) => Number.parseInt(hex.slice(start, start + 2), 16) / 255);
  const [red, green, blue] = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * red! + 0.7152 * green! + 0.0722 * blue!;
}
