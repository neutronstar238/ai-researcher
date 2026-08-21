import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalCss = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

test("matches the reference lifecycle flow instead of isolated card badges", () => {
  expect(rule(".lifecycle-card")).toEqual(expect.stringContaining("border: 0"));
  expect(rule(".lifecycle-card")).toEqual(expect.stringContaining("box-shadow: none"));
  expect(rule(".lifecycle-stage")).toEqual(expect.stringContaining("position: relative"));
  expect(rule(".lifecycle-stage:not(:last-child)::after")).toEqual(expect.stringContaining("height: 1px"));
  expect(rule(".lifecycle-stage:not(:last-child)::after")).toEqual(expect.stringContaining("background: var(--color-divider)"));
  expect(rule(".lifecycle-icon")).toEqual(expect.stringContaining("width: 64px"));
  expect(rule(".lifecycle-icon")).toEqual(expect.stringContaining("height: 64px"));
});

test("locks the canonical desktop Dashboard proportions and density", () => {
  expect(rule(".dashboard-grid")).toEqual(expect.stringContaining("grid-template-columns: minmax(0, 46fr) minmax(0, 54fr)"));
  expect(rule(".dashboard-grid")).toEqual(expect.stringContaining("gap: 8px"));
  expect(rule(".dashboard-primary-card")).toEqual(expect.stringContaining("min-height: 310px"));
  expect(rule(".dashboard-secondary-card")).toEqual(expect.stringContaining("min-height: 268px"));
  expect(rule(".system-health-bar")).toEqual(expect.stringContaining("min-height: 88px"));
});

test("uses the measured desktop brand and title scale", () => {
  expect(rule(".brand-block")).toEqual(expect.stringContaining("min-height: 196px"));
  expect(rule(".brand-logo")).toEqual(expect.stringContaining("width: 108px"));
  expect(rule(".brand-logo")).toEqual(expect.stringContaining("height: 108px"));
  expect(rule(".header-title")).toEqual(expect.stringContaining("font-size: 27px"));
});

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return globalCss.match(new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`))?.[1]?.replace(/\s+/g, " ").trim() ?? "";
}
