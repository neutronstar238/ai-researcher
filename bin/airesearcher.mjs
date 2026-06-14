#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(root, "src");
const args = ["-m", "autoresearch.cli.main", ...process.argv.slice(2)];
const env = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH ? `${src}${delimiter}${process.env.PYTHONPATH}` : src,
};

const candidates =
  process.platform === "win32"
    ? [
        ["py", ["-3"]],
        ["python", []],
        ["python3", []],
      ]
    : [
        ["python3", []],
        ["python", []],
      ];

let lastError = null;
for (const [command, prefix] of candidates) {
  const result = spawnSync(command, [...prefix, ...args], {
    cwd: root,
    env,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) {
    lastError = result.error;
    if (result.error.code === "ENOENT") {
      continue;
    }
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 0);
}

console.error(
  `Could not find a Python 3 interpreter. Last error: ${lastError?.message ?? "not found"}`,
);
process.exit(1);
